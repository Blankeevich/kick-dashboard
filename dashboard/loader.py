"""
Загрузчик выгрузок 1С в базу. Использует ту же логику, что проверенные парсеры.
Идемпотентность: файл с тем же хешем не грузится повторно;
новая выгрузка того же года ЗАМЕНЯЕТ старые факты (перезаливающая загрузка).
"""
import re
import hashlib
from datetime import datetime
import openpyxl
from django.db import transaction
from .models import Upload, SalesFact, SkuFact, DebtFact, DebtLine

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
STM = ['вкусвилл', 'самокат', 'старс', 'fancy', 'butman', 'зеленая линия', 'зелёная линия',
       'true', 'бионова', 'ригла', 'dermadrop', 'sport club', 'армения', 'молдова', 'дубай', 'на арабском']
NONPROD = ['шоу-бокс', 'набор', 'дисплей', 'п/ф', 'полуфабрикат', 'напиток']


def _num(x):
    if x in (None, ''):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace('\xa0', '').replace(' ', '').replace(',', '.'))
    except ValueError:
        return None


def _date(x):
    if isinstance(x, datetime):
        return x.date()
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', str(x or ''))
    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date() if m else None


def _hash(fileobj):
    fileobj.seek(0)
    h = hashlib.sha256(fileobj.read()).hexdigest()
    fileobj.seek(0)
    return h


def _read_rows(fileobj, filename=''):
    """Читает первый лист как список строк. Поддерживает и .xlsx (openpyxl), и старый .xls (xlrd)."""
    import io
    fileobj.seek(0)
    data = fileobj.read()
    fileobj.seek(0)
    name = (filename or getattr(fileobj, 'name', '') or '').lower()
    if name.endswith('.xls') and not name.endswith('.xlsx'):
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(0)
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == 3:  # дата в формате Excel
                    row.append(datetime(*xlrd.xldate_as_tuple(cell.value, book.datemode)))
                else:
                    row.append(cell.value if cell.value != '' else None)
            rows.append(tuple(row))
        return rows
    # .xlsx
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb['Лист_1'] if 'Лист_1' in wb.sheetnames else wb[wb.sheetnames[0]]
    return list(ws.iter_rows(values_only=True))


def _month_cols(header):
    cols, year = {}, None
    for j, c in enumerate(header):
        if not c:
            continue
        m = re.match(r'([а-я]{3})[а-я]*\.?\s*(\d{2})', str(c).lower())
        if m and m.group(1) in MONTHS:
            cols[MONTHS.index(m.group(1)) + 1] = j
            year = 2000 + int(m.group(2))
    return cols, year


def _classify(name):
    low = name.lower()
    if any(k in low for k in NONPROD):
        return 'non_product'
    if any(k in low for k in STM):
        return 'private_label'
    return 'own'


@transaction.atomic
def load_sales_client(fileobj, filename, user=None):
    h = _hash(fileobj)
    if Upload.objects.filter(kind='sales_client', file_hash=h).exists():
        return {'skipped': True, 'reason': 'Такой файл уже загружен (совпал хеш)'}
    rows = _read_rows(fileobj, filename)
    cols, year = _month_cols(rows[0])
    up = Upload.objects.create(kind='sales_client', filename=filename, file_hash=h,
                               period_year=year, uploaded_by=user)
    # перезаливка: удаляем прошлые факты этого года
    SalesFact.objects.filter(year=year).delete()
    facts, total = [], 0
    for r in rows[2:]:
        doc = r[0]
        if doc is None or str(doc).strip() in ('', 'Итого') or not r[2]:
            continue
        s = str(doc).strip()
        dt = ('Реализация' if s.startswith('Реализа') else 'Корректировка' if s.startswith('Корректировк')
              else 'Комиссионер' if s.startswith('Отчет комисс') else 'Прочее')
        for mnum, col in cols.items():
            amt = _num(r[col + 1])
            qty = _num(r[col])
            if amt is None and qty is None:
                continue
            facts.append(SalesFact(upload=up, doc_type=dt, doc_date=_date(r[1]),
                                   client=str(r[2]).strip(), manager=(str(r[3]).strip() if r[3] else ''),
                                   year=year, month=mnum, qty=qty or 0, amount=int(amt or 0)))
            total += int(amt or 0)
    SalesFact.objects.bulk_create(facts, batch_size=1000)
    up.rows_loaded = len(facts)
    up.control_sum = total
    up.save()
    return {'skipped': False, 'year': year, 'rows': len(facts), 'total': total}


@transaction.atomic
def load_sales_sku(fileobj, filename, user=None):
    h = _hash(fileobj)
    if Upload.objects.filter(kind='sales_sku', file_hash=h).exists():
        return {'skipped': True, 'reason': 'Такой файл уже загружен'}
    rows = _read_rows(fileobj, filename)
    cols, year = _month_cols(rows[0])
    up = Upload.objects.create(kind='sales_sku', filename=filename, file_hash=h,
                               period_year=year, uploaded_by=user)
    SkuFact.objects.filter(year=year).delete()
    facts, total = [], 0
    for r in rows[2:]:
        name = r[0]
        if name is None or str(name).strip() in ('', 'Итого'):
            continue
        name = str(name).strip()
        bt = _classify(name)
        for mnum, col in cols.items():
            amt = _num(r[col + 1])
            qty = _num(r[col])
            if amt is None and qty is None:
                continue
            facts.append(SkuFact(upload=up, sku_raw=name, brand_type=bt, year=year,
                                 month=mnum, qty=qty or 0, amount=int(amt or 0)))
            total += int(amt or 0)
    SkuFact.objects.bulk_create(facts, batch_size=1000)
    up.rows_loaded = len(facts)
    up.control_sum = total
    up.save()
    return {'skipped': False, 'year': year, 'rows': len(facts), 'total': total}


# корзины срока просрочки в новом отчёте (индексы колонок H..M)
_DEBT_BUCKETS = [(7, 'До 7 дн'), (8, '8–15 дн'), (9, '16–30 дн'),
                 (10, '31–40 дн'), (11, '41–90 дн'), (12, '>90 дн')]


def _parse_debt_new(rows, filename):
    """Новый формат «по срокам долга»: строка клиента + под ней реализации.
    Колонки: 0 Менеджер/Документ · 1 Покупатель · 2 Отгрузка · 3 Срок оплаты ·
    4 Долг · 5 Просрочено · 6 Дней · 7..12 корзины срока. Возвращает СЛОВАРИ (без записи в БД)."""
    m = re.search(r'на (\d{2})\.(\d{2})\.(\d{4})', filename)
    snap = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date() if m else None
    hdr = next((i for i, r in enumerate(rows)
                if len(r) > 1 and r[1] and str(r[1]).strip() == 'Покупатель'), None)
    if hdr is None:
        return [], [], 0
    facts, lines, total, cur = [], [], 0, None
    for r in rows[hdr + 2:]:
        a = str(r[0]).strip() if r[0] else ''
        b = str(r[1]).strip() if len(r) > 1 and r[1] else ''
        tot = _num(r[4])
        if b and b != 'Итого':                # строка клиента (Покупатель в колонке B)
            cur = b
            if tot:
                facts.append(dict(client=cur, manager=a, snapshot_date=snap,
                                  ship_date=_date(r[2]), due_date=_date(r[3]),
                                  debt_total=int(tot), debt_overdue=int(_num(r[5]) or 0),
                                  overdue_days=int(_num(r[6]) or 0)))
                total += int(tot)
        elif a and not b and cur and tot and a != 'Итого':   # любой документ под клиентом
            bucket = next((nm for idx, nm in _DEBT_BUCKETS if len(r) > idx and _num(r[idx])), '')
            mno = re.search(r'№\s*(\S+)', a)
            lines.append(dict(client=cur, doc_no=(mno.group(1) if mno else ''),
                              ship_date=_date(r[2]), due_date=_date(r[3]),
                              debt_total=int(tot), debt_overdue=int(_num(r[5]) or 0),
                              overdue_days=int(_num(r[6]) or 0), bucket=bucket))
    return facts, lines, total


def _parse_debt_old(rows):
    """Старый широкий формат: «Покупатель» в 1-й колонке. Возвращает словари."""
    hdr = next((i for i, r in enumerate(rows) if r[0] and str(r[0]).strip() == 'Покупатель'), None)
    if hdr is None:
        return [], [], 0
    facts, total = [], 0
    for r in rows[hdr + 1:]:
        client = r[0]
        if client is None or str(client).strip() in ('', 'Итого'):
            continue
        tot = _num(r[16])
        if tot is None:
            continue
        facts.append(dict(client=str(client).strip(),
                          manager=(str(r[5]).strip() if r[5] else ''),
                          ship_date=_date(r[11]), due_date=_date(r[13]),
                          debt_total=int(tot), debt_overdue=int(_num(r[18]) or 0),
                          overdue_days=int(_num(r[21]) or 0)))
        total += int(tot)
    return facts, [], total


@transaction.atomic
def load_debt(fileobj, filename, user=None):
    h = _hash(fileobj)
    if Upload.objects.filter(kind='debt', file_hash=h).exists():
        return {'skipped': True, 'reason': 'Такой файл уже загружен'}
    rows = _read_rows(fileobj, filename)
    # строгое распознавание нового формата: в шапке «Менеджер…» в кол.A и «Покупатель» в кол.B
    is_new = any(len(r) > 1 and r[1] and str(r[1]).strip() == 'Покупатель'
                 and r[0] and 'енеджер' in str(r[0]) for r in rows[:8])
    if is_new:
        facts, lines, total = _parse_debt_new(rows, filename)
    else:
        facts, lines, total = _parse_debt_old(rows)
    # ВАЖНО: не трогаем существующую дебиторку, пока разбор не дал непустой результат,
    # иначе кривой/чужой файл обнулит данные
    if not facts:
        return {'skipped': True, 'reason': 'Формат не распознан или нет строк — данные не изменены'}
    up = Upload.objects.create(kind='debt', filename=filename, file_hash=h, uploaded_by=user)
    DebtFact.objects.all().delete()        # дебиторка — всегда актуальный снимок
    DebtLine.objects.all().delete()
    DebtFact.objects.bulk_create([DebtFact(upload=up, **d) for d in facts], batch_size=1000)
    DebtLine.objects.bulk_create([DebtLine(upload=up, **d) for d in lines], batch_size=1000)
    up.rows_loaded = len(facts)
    up.control_sum = total
    up.save()
    return {'skipped': False, 'rows': len(facts), 'lines': len(lines), 'total': total}
