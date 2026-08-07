"""
Витрины: агрегация фактов из базы в цифры для дашборда.
Фильтры: год ИЛИ произвольный период (date_from/date_to), менеджер, канал, контрагент.
"""
from datetime import date
from django.db.models import Sum
from .models import SalesFact, SkuFact, DebtFact, Client

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def _excluded():
    return set(Client.objects.filter(excluded=True).values_list('name', flat=True))


def _clients_in_channel(channel):
    return set(Client.objects.filter(channel=channel).values_list('name', flat=True))


def sales_qs(year=None, manager=None, channel=None, client=None, date_from=None, date_to=None):
    """Queryset продаж. Если задан период (date_from/date_to) — фильтр по дате документа,
    иначе по году."""
    qs = SalesFact.objects.exclude(client__in=_excluded())
    if date_from and date_to:
        qs = qs.filter(doc_date__range=[date_from, date_to])
    elif year:
        qs = qs.filter(year=year)
    if manager:
        qs = qs.filter(manager=manager)
    if client:
        qs = qs.filter(client=client)
    if channel:
        qs = qs.filter(client__in=_clients_in_channel(channel))
    return qs


def sales_summary(year=None, **f):
    qs = sales_qs(year, **f)
    total = qs.aggregate(s=Sum('amount'))['s'] or 0
    returns = qs.filter(amount__lt=0).aggregate(s=Sum('amount'))['s'] or 0
    by_month = [0] * 12
    for row in qs.values('month').annotate(s=Sum('amount')):
        by_month[row['month'] - 1] = row['s'] or 0
    return {'total': total, 'returns': returns, 'by_month': by_month}


def all_clients(year=None, **f):
    qs = sales_qs(year, **f)
    total = qs.aggregate(s=Sum('amount'))['s'] or 1
    rows = qs.values('client').annotate(s=Sum('amount')).order_by('-s')
    return [{'name': r['client'], 'amount': r['s'], 'share': round(r['s'] / total * 100, 1)} for r in rows]


def top_clients(year=None, limit=5, **f):
    return all_clients(year, **f)[:limit]


def by_manager(year=None, **f):
    f2 = {k: v for k, v in f.items() if k != 'manager'}
    qs = sales_qs(year, **f2)
    rows = qs.values('manager').annotate(s=Sum('amount')).order_by('-s')
    total = sum(r['s'] for r in rows) or 1
    out = []
    for r in rows:
        clients = qs.filter(manager=r['manager']).values('client').distinct().count()
        out.append({'manager': r['manager'] or '—', 'amount': r['s'],
                    'share': round(r['s'] / total * 100, 1), 'clients': clients})
    return out


def sales_by_day(year=None, month=None, **f):
    qs = sales_qs(year, **f).filter(doc_date__isnull=False, amount__gt=0)
    # при заданном периоде — по всем дням периода
    if f.get('date_from') and f.get('date_to'):
        rows = qs.values('doc_date').annotate(s=Sum('amount')).order_by('doc_date')
        return {'month': None, 'month_name': 'период',
                'days': [{'day': r['doc_date'].strftime('%d.%m'), 'amount': r['s']} for r in rows]}
    if month is None:
        last = qs.order_by('-doc_date').values_list('doc_date', flat=True).first()
        if not last:
            return {'month': None, 'month_name': '', 'days': []}
        month = last.month
    rows = (qs.filter(doc_date__month=month).values('doc_date')
            .annotate(s=Sum('amount')).order_by('doc_date'))
    return {'month': month, 'month_name': MONTHS[month - 1],
            'days': [{'day': r['doc_date'].day, 'amount': r['s']} for r in rows]}


# строки-документы, которые не должны попадать в список SKU
_DOC_PREFIXES = ('Реализация', 'Корректировка', 'Отчет комисс', 'Отчёт комисс', 'Операция', 'Возврат', 'Списание')


def top_sku(year=None, limit=8):
    qs = SkuFact.objects.filter(year=year) if year else SkuFact.objects.all()
    rows = qs.values('sku_raw').annotate(s=Sum('amount'), q=Sum('qty')).order_by('-s')
    out = []
    for r in rows:
        if str(r['sku_raw']).strip().startswith(_DOC_PREFIXES):
            continue  # это строка-документ, не товар
        out.append({'name': r['sku_raw'], 'amount': r['s'], 'qty': int(r['q'] or 0),
                    'price': round(r['s'] / r['q']) if r['q'] else 0})
        if len(out) >= limit:
            break
    return out


def _latest_debt_date():
    from django.db.models import Max
    return DebtFact.objects.aggregate(d=Max('snapshot_date'))['d']


def debt_dates():
    """Все даты снимков дебиторки (новые сверху) — для селектора."""
    from .models import DebtSnapshot
    return list(DebtSnapshot.objects.order_by('-date').values_list('date', flat=True))


def debt_summary(manager=None, client=None, only_overdue=False, min_amount=1000,
                 order='-debt_total', snapshot=None):
    snap = snapshot or _latest_debt_date()
    qs = (DebtFact.objects.filter(snapshot_date=snap)
          .exclude(client__in=_excluded()).filter(debt_total__gte=min_amount))
    if manager:
        qs = qs.filter(manager=manager)
    if client:
        qs = qs.filter(client=client)
    if only_overdue:
        qs = qs.filter(debt_overdue__gt=0)
    total = qs.aggregate(s=Sum('debt_total'))['s'] or 0
    overdue = qs.aggregate(s=Sum('debt_overdue'))['s'] or 0
    allowed = {'-debt_total', 'debt_total', '-overdue_days', 'overdue_days', 'due_date', '-due_date', 'client'}
    if order not in allowed:
        order = '-debt_total'
    debtors = list(qs.order_by(order).values(
        'client', 'manager', 'debt_total', 'debt_overdue', 'overdue_days', 'due_date'))
    limits = dict(Client.objects.exclude(credit_limit__isnull=True)
                  .values_list('name', 'credit_limit'))
    deltas, _prev = debt_client_deltas(snap)
    for d in debtors:                       # кредитный лимит, флаг превышения, динамика
        lim = limits.get(d['client'])
        d['credit_limit'] = lim
        d['over_limit'] = bool(lim) and d['debt_total'] > lim
        dl = deltas.get(d['client'])
        d['delta'] = dl
        d['delta_abs'] = abs(dl) if dl else 0
    return {'total': total, 'overdue': overdue,
            'share': round(overdue / total * 100, 1) if total else 0,
            'count': qs.count(), 'debtors': debtors}


def schet_map():
    """Реализация (doc_no) → номер счёта на оплату (00БП-…), из продаж."""
    return dict(SalesFact.objects.exclude(schet_no='').exclude(doc_no='')
                .values_list('doc_no', 'schet_no'))


def debt_lines(client, snapshot=None):
    """Реализации, формирующие долг клиента (расшифровка из 1С). Просроченные — сверху."""
    from .models import DebtLine
    snap = snapshot or _latest_debt_date()
    rows = list(DebtLine.objects.filter(client=client, snapshot_date=snap)
                .order_by('-debt_overdue', 'due_date', '-debt_total')
                .values('doc_no', 'ship_date', 'due_date', 'debt_total',
                        'debt_overdue', 'overdue_days', 'bucket'))
    smap = schet_map()
    for r in rows:  # светофор: красный >30 дн · жёлтый просрочен · зелёный в сроке
        r['light'] = 'red' if r['overdue_days'] > 30 else 'amb' if r['overdue_days'] > 0 else 'green'
        r['schet'] = smap.get(r['doc_no'], '')
    return rows


def _debt_ref_date():
    from django.db.models import Max
    return DebtFact.objects.aggregate(d=Max('snapshot_date'))['d'] or date.today()


def debt_aging(manager=None, client=None, snapshot=None):
    """Кошельки (просрочено / к оплате на неделе / в сроке) и корзины срока долга."""
    from datetime import timedelta
    from .models import DebtLine
    snap = snapshot or _latest_debt_date()
    ref = snap or date.today()
    scope = DebtFact.objects.filter(snapshot_date=snap).exclude(client__in=_excluded())
    if manager:
        scope = scope.filter(manager=manager)
    if client:
        scope = scope.filter(client=client)
    names = set(scope.values_list('client', flat=True))
    lines = DebtLine.objects.filter(client__in=names, snapshot_date=snap)
    overdue = week = future = 0
    buckets = {nm: 0 for nm in ['До 7 дн', '8–15 дн', '16–30 дн', '31–40 дн', '41–90 дн', '>90 дн']}
    horizon = ref + timedelta(days=7)
    for l in lines.values('debt_total', 'debt_overdue', 'due_date', 'bucket'):
        overdue += l['debt_overdue']
        rest = l['debt_total'] - l['debt_overdue']            # ещё не просроченная часть
        if rest > 0:
            if l['due_date'] and l['due_date'] <= horizon:
                week += rest
            else:
                future += rest
        if l['bucket'] in buckets:
            buckets[l['bucket']] += l['debt_total']
    return {'ref_date': ref, 'overdue': overdue, 'week': week, 'future': future,
            'buckets': [{'name': k, 'amount': v} for k, v in buckets.items()]}


def debt_history(limit=12):
    """История долга по снимкам (для графика динамики)."""
    from .models import DebtSnapshot
    rows = list(DebtSnapshot.objects.order_by('date').values('date', 'total', 'overdue', 'count'))
    return rows[-limit:]


def debt_client_deltas(snapshot=None):
    """Изменение долга по клиентам: выбранный снимок минус предыдущий. >0 растёт, <0 гасит."""
    from .models import DebtSnapshot, DebtClientSnapshot
    dates = list(DebtSnapshot.objects.order_by('-date').values_list('date', flat=True))
    if len(dates) < 2:
        return {}, None
    i = dates.index(snapshot) if snapshot in dates else 0
    if i + 1 >= len(dates):
        return {}, None
    cur_d, prev_d = dates[i], dates[i + 1]
    cur = dict(DebtClientSnapshot.objects.filter(date=cur_d).values_list('client', 'debt_total'))
    prev = dict(DebtClientSnapshot.objects.filter(date=prev_d).values_list('client', 'debt_total'))
    deltas = {c: cur[c] - prev.get(c, 0) for c in cur}
    return deltas, prev_d


def client_sales(client, limit=100):
    """Реализации клиента (для расшифровки по клику из дебиторки).
    Приблизительно: все продажи клиента с датами. Точная привязка к долгу —
    после выгрузки расшифровки дебиторки из 1С."""
    qs = (SalesFact.objects.filter(client=client, amount__gt=0)
          .order_by('-doc_date').values('doc_date', 'doc_type', 'amount', 'manager', 'year')[:limit])
    return list(qs)


def sales_years():
    """Годы, за которые есть продажи (новые сверху) — для селектора года на графиках."""
    return sorted(set(SalesFact.objects.values_list('year', flat=True)), reverse=True)


def _sku_norm(s):
    """Ключ SKU без хвоста «, шт» и лишних пробелов — чтобы 2025 и 2026 сходились."""
    import re
    s = str(s or '').replace('\xa0', ' ')
    s = re.sub(r'\s*,?\s*шт\.?\s*$', '', s, flags=re.I)
    return re.sub(r'\s+', ' ', s).strip()


def sku_year_detail(q=''):
    """Все SKU × годы: объём (шт), выручка, средняя цена продажи за штуку.
    Позиции схлопываются по нормализованному имени (без «, шт»)."""
    from collections import defaultdict
    years = sorted(set(SkuFact.objects.values_list('year', flat=True)))
    if not years:
        return {'years': [], 'rows': []}
    per = defaultdict(lambda: defaultdict(lambda: {'amount': 0, 'qty': 0}))
    disp = {}
    for r in SkuFact.objects.values('sku_raw', 'year').annotate(a=Sum('amount'), qt=Sum('qty')):
        name = r['sku_raw']
        if not name or str(name).strip().startswith(_DOC_PREFIXES):
            continue
        clean = _sku_norm(name)
        key = clean.lower()
        disp.setdefault(key, clean)
        cell = per[key][r['year']]
        cell['amount'] += round(r['a'] or 0)
        cell['qty'] += int(r['qt'] or 0)
    ql = (q or '').strip().lower()
    rows = []
    for key, d in per.items():
        if ql and ql not in key:
            continue
        cells = []
        for y in years:
            c = d.get(y)
            if c and c['qty']:
                cells.append({'year': y, 'amount': c['amount'], 'qty': c['qty'],
                              'price': round(c['amount'] / c['qty']) if c['qty'] else 0, 'has': True})
            elif c and c['amount']:
                cells.append({'year': y, 'amount': c['amount'], 'qty': 0, 'price': 0, 'has': True})
            else:
                cells.append({'year': y, 'amount': 0, 'qty': 0, 'price': 0, 'has': False})
        rows.append({'name': disp[key], 'cells': cells, 'total': sum(c['amount'] for c in cells)})
    rows.sort(key=lambda r: -r['total'])
    return {'years': years, 'rows': rows}


def client_year_detail(q=''):
    """Все клиенты × годы: выручка, объём (шт), число отгрузок, средний чек."""
    from collections import defaultdict
    from django.db.models import Count
    excl = _excluded()
    years = sorted(set(SalesFact.objects.values_list('year', flat=True)))
    if not years:
        return {'years': [], 'rows': []}
    per = defaultdict(lambda: {})
    for r in (SalesFact.objects.exclude(client__in=excl).values('client', 'year')
              .annotate(a=Sum('amount'), qt=Sum('qty'), n=Count('doc_no', distinct=True))):
        name = r['client']
        if not name:
            continue
        orders = r['n'] or 0
        per[name][r['year']] = {'amount': round(r['a'] or 0), 'qty': int(r['qt'] or 0),
                                'orders': orders, 'check': round((r['a'] or 0) / orders) if orders else 0}
    ql = (q or '').strip().lower()
    rows = []
    for name, d in per.items():
        if ql and ql not in name.lower():
            continue
        cells = []
        for y in years:
            c = d.get(y)
            cells.append({'year': y, 'amount': c['amount'] if c else 0, 'qty': c['qty'] if c else 0,
                          'orders': c['orders'] if c else 0, 'check': c['check'] if c else 0, 'has': bool(c)})
        rows.append({'name': name, 'cells': cells, 'total': sum(c['amount'] for c in cells)})
    rows.sort(key=lambda r: -r['total'])
    return {'years': years, 'rows': rows}


def _matrix(base_qs, field, years, limit=10, exclude_docs=False, norm=None):
    """Топ-сущности (клиент/менеджер/SKU) × годы — матрица выручки.
    norm — функция нормализации имени (напр. схлопнуть «, шт» у SKU)."""
    from collections import defaultdict
    per = defaultdict(dict)
    disp = {}
    qs = base_qs.values(field, 'year').annotate(s=Sum('amount'))
    for r in qs:
        name = r[field]
        if not name:
            continue
        if exclude_docs and str(name).strip().startswith(_DOC_PREFIXES):
            continue
        if norm:
            clean = norm(name)
            key = clean.lower()
            disp.setdefault(key, clean)
        else:
            key = name
            disp.setdefault(key, name)
        per[key][r['year']] = per[key].get(r['year'], 0) + (r['s'] or 0)
    rows = [{'name': disp[k], 'by_year': [v.get(y, 0) for y in years], 'total': sum(v.values())}
            for k, v in per.items()]
    rows.sort(key=lambda r: -r['total'])
    return rows[:limit]


_SIZE_BUCKETS = [(0, 100000, '0–100к ₽'), (100000, 500000, '100к–500к ₽'), (500000, None, '500к+ ₽')]


def _year_client_sales(year):
    return {r['client']: (r['s'] or 0) for r in
            SalesFact.objects.filter(year=year).exclude(client__in=_excluded())
            .values('client').annotate(s=Sum('amount')) if (r['s'] or 0) > 0}


def segments_matrix(years):
    """Клиенты по размеру годовой выручки (корзины) × годы — количество."""
    per = {y: _year_client_sales(y) for y in years}
    out = []
    for lo, hi, label in _SIZE_BUCKETS:
        cells = []
        for y in years:
            cnt = sum(1 for v in per[y].values() if v >= lo and (hi is None or v < hi))
            cells.append({'year': y, 'count': cnt})
        out.append({'label': label, 'lo': lo, 'hi': hi or '', 'cells': cells})
    return out


def bucket_clients(year, lo, hi):
    """Клиенты в корзине размера за год."""
    rows = [{'name': c, 'sales': v} for c, v in _year_client_sales(year).items()
            if v >= lo and (hi is None or v < hi)]
    rows.sort(key=lambda r: -r['sales'])
    return rows


def lost_clients(year):
    """Клиенты, которые покупали в предыдущем году, но не в этом (отток)."""
    cur = set(_year_client_sales(year))
    prev = _year_client_sales(year - 1)
    rows = [{'name': c, 'sales': v} for c, v in prev.items() if c not in cur]
    rows.sort(key=lambda r: -r['sales'])
    return rows


def forgotten_clients(current_year):
    """Забытые клиенты: покупали когда-либо раньше, но в текущем году — ни разу."""
    from collections import defaultdict
    excl = _excluded()
    cur = set(SalesFact.objects.filter(year=current_year, amount__gt=0)
              .exclude(client__in=excl).values_list('client', flat=True))
    hist = defaultdict(lambda: {'total': 0, 'last': 0})
    for r in (SalesFact.objects.filter(year__lt=current_year, amount__gt=0).exclude(client__in=excl)
              .values('client', 'year').annotate(s=Sum('amount'))):
        h = hist[r['client']]
        h['total'] += r['s'] or 0
        h['last'] = max(h['last'], r['year'])
    rows = [{'name': c, 'sales': d['total'], 'last': d['last']}
            for c, d in hist.items() if c not in cur]
    rows.sort(key=lambda r: -r['sales'])
    return rows


def managers_list(year):
    """Список менеджеров: выручка за год, клиентов, долг под ответственностью."""
    from django.db.models import Count
    excl = _excluded()
    rows = {}
    for r in (SalesFact.objects.filter(year=year).exclude(client__in=excl).exclude(manager='')
              .values('manager').annotate(s=Sum('amount'), c=Count('client', distinct=True))):
        rows[r['manager']] = {'manager': r['manager'], 'sales': r['s'] or 0, 'clients': r['c'], 'debt': 0}
    snap = _latest_debt_date()
    for r in (DebtFact.objects.filter(snapshot_date=snap).exclude(client__in=excl).exclude(manager='')
              .values('manager').annotate(s=Sum('debt_total'))):
        if r['manager'] in rows:
            rows[r['manager']]['debt'] = r['s'] or 0
        else:
            rows[r['manager']] = {'manager': r['manager'], 'sales': 0, 'clients': 0, 'debt': r['s'] or 0}
    return sorted(rows.values(), key=lambda x: -x['sales'])


def manager_profile(manager):
    """Портрет менеджера: выручка по годам, план/факт, его клиенты, кто замолчал, долг."""
    from django.db.models import Max
    excl = _excluded()
    today = date.today()
    years = sorted(set(SalesFact.objects.values_list('year', flat=True)))
    cur_year = max(years) if years else None
    by_year = [{'year': y, 'total': (SalesFact.objects.filter(manager=manager, year=y)
                .exclude(client__in=excl).aggregate(s=Sum('amount'))['s'] or 0)} for y in years]
    cli = {}
    for r in (SalesFact.objects.filter(manager=manager, amount__gt=0, doc_date__isnull=False)
              .exclude(client__in=excl).values('client').annotate(last=Max('doc_date'), tot=Sum('amount'))):
        cli[r['client']] = {'last': r['last'], 'total': r['tot'], 'days': (today - r['last']).days}
    cy = {r['client']: r['s'] for r in SalesFact.objects.filter(manager=manager, year=cur_year)
          .exclude(client__in=excl).values('client').annotate(s=Sum('amount'))}
    snap = _latest_debt_date()
    db = {r['client']: r['s'] for r in DebtFact.objects.filter(snapshot_date=snap, manager=manager)
          .values('client').annotate(s=Sum('debt_total'))}
    rows = [{'client': c, 'cy': cy.get(c, 0), 'total': v['total'], 'days': v['days'],
             'last': v['last'], 'debt': db.get(c, 0)} for c, v in cli.items()]
    rows.sort(key=lambda r: -(r['cy'] or 0))
    silent = sorted([r for r in rows if r['days'] >= 60 and r['total'] > 200000],
                    key=lambda r: -r['total'])
    return {'manager': manager, 'by_year': by_year, 'cur_year': cur_year,
            'clients': rows, 'silent': silent, 'plans': plan_status(manager=manager),
            'sales_cur': sum(cy.values()), 'debt_total': sum(db.values()), 'n_clients': len(rows)}


def rfm():
    """RFM-сегментация + ABC клиентов на основе продаж (без новых данных)."""
    from datetime import date as _d
    from django.db.models import Max, Count
    today = _d.today()
    excl = _excluded()
    data = []
    for r in (SalesFact.objects.exclude(client__in=excl).filter(amount__gt=0, doc_date__isnull=False)
              .values('client').annotate(last=Max('doc_date'), m=Sum('amount'),
                                         f=Count('doc_date', distinct=True))):
        data.append({'client': r['client'], 'r_days': (today - r['last']).days,
                     'last': r['last'], 'm': r['m'] or 0, 'f': r['f']})
    if not data:
        return {'segments': [], 'rows': [], 'total_clients': 0}

    def q(vals, frac):
        s = sorted(vals)
        return s[min(int(len(s) * frac), len(s) - 1)]
    rt1, rt2 = q([d['r_days'] for d in data], .33), q([d['r_days'] for d in data], .66)
    ft1, ft2 = q([d['f'] for d in data], .33), q([d['f'] for d in data], .66)
    mt1, mt2 = q([d['m'] for d in data], .33), q([d['m'] for d in data], .66)

    def sc(v, t1, t2):
        return 1 if v <= t1 else 2 if v <= t2 else 3

    def seg(R, F, M):
        if R >= 3 and F >= 2 and M >= 2:
            return 'Чемпионы'
        if M >= 3 and R <= 1:
            return 'Крупные под угрозой'
        if R >= 3 and F <= 1:
            return 'Новички'
        if F >= 2 and M >= 2:
            return 'Лояльные'
        if R <= 1:
            return 'Спящие'
        return 'Обычные'

    for d in data:
        d['R'] = 3 if d['r_days'] <= rt1 else 2 if d['r_days'] <= rt2 else 1
        d['F'] = sc(d['f'], ft1, ft2)
        d['M'] = sc(d['m'], mt1, mt2)
        d['seg'] = seg(d['R'], d['F'], d['M'])
    # ABC по накопленной доле выручки
    data.sort(key=lambda x: -x['m'])
    tot = sum(d['m'] for d in data) or 1
    cum = 0
    for d in data:
        cum += d['m']
        share = cum / tot * 100
        d['abc'] = 'A' if share <= 80 else 'B' if share <= 95 else 'C'
    # сводка по сегментам
    order = ['Чемпионы', 'Лояльные', 'Новички', 'Крупные под угрозой', 'Спящие', 'Обычные']
    summ = {s: {'seg': s, 'count': 0, 'revenue': 0} for s in order}
    for d in data:
        summ[d['seg']]['count'] += 1
        summ[d['seg']]['revenue'] += d['m']
    return {'segments': [summ[s] for s in order if summ[s]['count']],
            'rows': data, 'total_clients': len(data)}


def cost_margin(vat=0.22, group=None):
    """Себестоимость + маржа по позициям: себест (без НДС и с НДС), цена продажи, маржа.
    group — фильтр по своей группе позиций (CostGroup)."""
    from django.db.models import Max
    from .models import CostItem
    import re
    def _n(s):   # нормализуем имя SKU: убираем хвост «, шт», регистр, лишние пробелы
        return re.sub(r'\s*,?\s*шт\.?\s*$', '', str(s or '').strip(), flags=re.I).strip().lower()
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    price, rev, qty = {}, {}, {}
    if ly:
        for r in SkuFact.objects.filter(year=ly, qty__gt=0).values('sku_raw').annotate(a=Sum('amount'), q=Sum('qty')):
            if r['q']:
                k = _n(r['sku_raw'])
                price[k] = r['a'] / r['q']    # цена с НДС, ключ нормализован
                rev[k] = r['a']
                qty[k] = r['q']
    mapped, unmapped, nocost = [], [], []
    items = CostItem.objects.prefetch_related('skus')
    if group is not None:
        items = items.filter(groups=group)
    for it in items:
        if not it.cost or it.cost <= 0:          # себестоимость ещё не задана
            nocost.append({'line': it.line, 'name': it.name})
            continue
        cost_vat = round(it.cost * (1 + vat))
        # цена своего бренда: первый привязанный SKU, у которого есть продажи
        p = None
        pk = None
        for s in [it.sku] + [x.sku for x in it.skus.all()]:
            if s and _n(s) in price:
                p = price[_n(s)]
                pk = _n(s)
                break
        if p:
            margin = p - cost_vat               # маржа с НДС
            mapped.append({'line': it.line, 'name': it.name,
                           'cost_vat': cost_vat, 'price': round(p), 'margin': round(margin),
                           'mp': round(margin / p * 100) if p else 0,
                           'rev': round(rev.get(pk, 0))})       # выручка позиции — вес
        else:
            unmapped.append({'line': it.line, 'name': it.name, 'cost_vat': cost_vat})
    mapped.sort(key=lambda r: r['mp'])
    tot_rev = sum(r['rev'] for r in mapped)
    return {'mapped': mapped, 'unmapped': unmapped, 'nocost': nocost, 'year': ly, 'vat_pct': round(vat * 100),
            # средневзвешенная маржа по выручке (батончик на 4 млн весит больше, чем на 50к)
            'avg_margin': round(sum(r['mp'] * r['rev'] for r in mapped) / tot_rev) if tot_rev else 0,
            'avg_margin_simple': round(sum(r['mp'] for r in mapped) / len(mapped)) if mapped else 0}


def _cost_by_sku():
    """Себестоимость по нормализованному имени SKU (свой + привязанные СТМ)."""
    import re
    from .models import CostItem
    def _n(s):
        return re.sub(r'\s*,?\s*шт\.?\s*$', '', str(s or '').strip(), flags=re.I).strip().lower()
    d = {}
    for it in CostItem.objects.prefetch_related('skus'):
        if not it.cost or it.cost <= 0:          # себестоимость не задана — пропускаем
            continue
        for s in [it.sku] + [x.sku for x in it.skus.all()]:
            if s:
                d[_n(s)] = it.cost
    return d, _n


def _recipe_by_sku():
    """Нормализованное имя SKU → наш рецепт (id, название, себестоимость).
    Все СТМ-варианты, привязанные к одному рецепту, ведут на одну нашу позицию."""
    import re
    from .models import CostItem
    def _n(s):
        return re.sub(r'\s*,?\s*шт\.?\s*$', '', str(s or '').strip(), flags=re.I).strip().lower()
    m = {}
    for it in CostItem.objects.prefetch_related('skus'):
        c = it.cost if (it.cost and it.cost > 0) else None   # 0 = себестоимость не задана
        for s in [it.sku] + [x.sku for x in it.skus.all()]:
            if s:
                m[_n(s)] = (it.id, it.name, c)
    return m, _n


def _doc_channel_map(ly):
    """doc_no → (client, channel_code) за год."""
    ch_of = dict(Client.objects.values_list('name', 'channel'))
    m = {}
    for r in SalesFact.objects.filter(year=ly).exclude(doc_no='').values('doc_no', 'client').distinct():
        m[r['doc_no']] = (r['client'], ch_of.get(r['client'], 'прочее'))
    return m


def _purchases_margin(docs, vat=0.22):
    """Маржа по набору документов, свёрнуто в НАШИ позиции (рецепты).
    Все SKU (свой бренд + СТМ), привязанные к одному рецепту, собираются в одну строку."""
    from collections import defaultdict
    from django.db.models import Max
    from .models import SkuDoc
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not ly or not docs:
        return {'rows': [], 'total_rev': 0, 'total_margin': 0}
    rec_by, _n = _recipe_by_sku()
    # key: ('rec', id) для наших позиций, ('raw', sku) для непривязанных
    agg = defaultdict(lambda: {'qty': 0, 'amount': 0, 'name': None, 'cost': None})
    for d in SkuDoc.objects.filter(year=ly, doc_no__in=docs).values('sku_raw', 'qty', 'amount'):
        rec = rec_by.get(_n(d['sku_raw']))
        if rec:
            key, name, cost = ('rec', rec[0]), rec[1], rec[2]
        else:
            key, name, cost = ('raw', d['sku_raw']), d['sku_raw'], None
        a = agg[key]
        a['qty'] += d['qty']
        a['amount'] += d['amount']
        a['name'] = name
        a['cost'] = cost
    rows = []
    for _key, v in agg.items():
        if v['qty'] <= 0:
            continue
        price = v['amount'] / v['qty']          # цена с НДС (средневзвешенная по продажам)
        cost = v['cost']
        cost_vat = cost * (1 + vat) if cost is not None else None
        r = {'sku': v['name'], 'qty': int(v['qty']), 'revenue': round(v['amount']),
             'price': round(price), 'cost': round(cost_vat) if cost_vat is not None else None}
        if cost_vat is not None:
            margin = price - cost_vat           # маржа с НДС
            r.update({'margin': round(margin), 'margin_sum': round(margin * v['qty']),
                      'mp': round(margin / price * 100) if price else 0})
        rows.append(r)
    rows.sort(key=lambda x: -x['revenue'])
    total_margin = round(sum(r.get('margin_sum', 0) for r in rows))
    covered_rev = sum(r['revenue'] for r in rows if r['cost'] is not None)
    return {'rows': rows, 'total_rev': round(sum(r['revenue'] for r in rows)),
            'total_margin': total_margin,
            'avg_mp': round(total_margin / covered_rev * 100) if covered_rev else 0,
            'covered': sum(1 for r in rows if r['cost'] is not None)}


def group_report(clients, vat=0.22):
    """Маржа по реальным покупкам контрагентов группы."""
    from django.db.models import Max
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not ly or not clients:
        return {'rows': [], 'total_rev': 0, 'total_margin': 0}
    docs = set(SalesFact.objects.filter(year=ly, client__in=clients)
               .exclude(doc_no='').values_list('doc_no', flat=True))
    return _purchases_margin(docs, vat)


def manager_report(manager, vat=0.22):
    """Маржа по реальным продажам менеджера."""
    from django.db.models import Max
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not ly or not manager:
        return {'rows': [], 'total_rev': 0, 'total_margin': 0}
    docs = set(SalesFact.objects.filter(year=ly, manager=manager)
               .exclude(doc_no='').values_list('doc_no', flat=True))
    return _purchases_margin(docs, vat)


def channel_positions(code, vat=0.22):
    """Что берёт канал: позиции (SKU) с объёмом, ценой, себестоимостью и маржой."""
    from collections import defaultdict
    from django.db.models import Max
    from .models import SkuDoc
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not ly:
        return {'rows': [], 'label': code}
    cost_by, _n = _cost_by_sku()
    doc2 = _doc_channel_map(ly)
    agg = defaultdict(lambda: {'qty': 0, 'amount': 0})
    for d in SkuDoc.objects.filter(year=ly).values('doc_no', 'sku_raw', 'qty', 'amount'):
        cc = doc2.get(d['doc_no'])
        if not cc or cc[1] != code:
            continue
        a = agg[d['sku_raw']]
        a['qty'] += d['qty']
        a['amount'] += d['amount']
    rows = []
    for sku, v in agg.items():
        if v['qty'] <= 0:
            continue
        price = v['amount'] / v['qty']
        price_nv = price / (1 + vat)
        cost = cost_by.get(_n(sku))
        r = {'sku': sku, 'qty': int(v['qty']), 'revenue': round(v['amount']),
             'price': round(price), 'cost': round(cost) if cost is not None else None}
        if cost is not None:
            margin = price_nv - cost
            r.update({'margin': round(margin), 'margin_sum': round(margin * v['qty']),
                      'mp': round(margin / price_nv * 100) if price_nv else 0})
        rows.append(r)
    rows.sort(key=lambda x: -x['revenue'])
    label = dict(Client.CHANNELS).get(code, code)
    return {'rows': rows, 'label': label, 'code': code,
            'total_rev': round(sum(r['revenue'] for r in rows) / (1 + vat)),
            'total_margin': round(sum(r.get('margin_sum', 0) for r in rows))}


def channel_margin(vat=0.22):
    """Маржа в разрезе КАНАЛОВ клиентов: сшиваем номенклатуру×контрагент по номеру документа,
    берём себестоимость по SKU и канал клиента."""
    import re
    from collections import defaultdict
    from django.db.models import Max
    from .models import SkuDoc, CostItem
    def _n(s):
        return re.sub(r'\s*,?\s*шт\.?\s*$', '', str(s or '').strip(), flags=re.I).strip().lower()
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not ly:
        return {'channels': [], 'total_rev': 0, 'total_margin': 0, 'covered': 0}
    # себестоимость по нормализованному имени SKU
    cost_by = {}
    for it in CostItem.objects.prefetch_related('skus'):
        for s in [it.sku] + [x.sku for x in it.skus.all()]:
            if s:
                cost_by[_n(s)] = it.cost
    # документ → канал клиента (за последний год)
    channel_of = dict(Client.objects.values_list('name', 'channel'))
    doc2ch = {}
    for r in SalesFact.objects.filter(year=ly).exclude(doc_no='').values('doc_no', 'client').distinct():
        doc2ch[r['doc_no']] = channel_of.get(r['client'], 'прочее')
    # агрегируем по каналам: выручка (без НДС) и маржа
    agg = defaultdict(lambda: {'rev_nv': 0, 'margin': 0, 'qty': 0})
    covered_rev = 0
    for d in SkuDoc.objects.filter(year=ly).values('doc_no', 'sku_raw', 'qty', 'amount'):
        ch = doc2ch.get(d['doc_no'])
        if ch is None:
            continue
        cost = cost_by.get(_n(d['sku_raw']))
        rev_nv = d['amount'] / (1 + vat)
        a = agg[ch]
        a['rev_nv'] += rev_nv
        a['qty'] += d['qty']
        if cost is not None:
            a['margin'] += rev_nv - cost * d['qty']
            covered_rev += rev_nv
    labels = dict(Client.CHANNELS)
    channels = [{'channel': labels.get(k, k), 'code': k, 'revenue': round(v['rev_nv']),
                 'margin': round(v['margin']), 'qty': int(v['qty']),
                 'mp': round(v['margin'] / v['rev_nv'] * 100) if v['rev_nv'] else 0}
                for k, v in agg.items()]
    channels.sort(key=lambda r: -r['revenue'])
    tr = sum(c['revenue'] for c in channels)
    return {'channels': channels, 'total_rev': tr,
            'total_margin': round(sum(c['margin'] for c in channels)),
            'covered_pct': round(covered_rev / tr * 100) if tr else 0}


def signals():
    """Сигналы «что требует внимания»: замолчавшие клиенты, рост долга, превышение лимита, падение SKU."""
    from datetime import timedelta
    from django.db.models import Max, Count
    today = date.today()
    excl = _excluded()

    # 1) крупный клиент замолчал (нет заказов ≥ 60 дней, историческая выручка значима)
    silent = []
    for r in (SalesFact.objects.exclude(client__in=excl).filter(doc_date__isnull=False, amount__gt=0)
              .values('client').annotate(last=Max('doc_date'), tot=Sum('amount'))):
        days = (today - r['last']).days
        if days >= 60 and r['tot'] > 300000:
            silent.append({'client': r['client'], 'days': days, 'last': r['last'], 'total': r['tot']})
    silent.sort(key=lambda x: -x['total'])

    # 2) долг растёт (между двумя последними снимками)
    deltas, prev_d = debt_client_deltas(_latest_debt_date())
    debt_up = sorted([{'client': c, 'delta': d} for c, d in deltas.items() if d > 50000],
                     key=lambda x: -x['delta'])

    # 3) превышен кредитный лимит
    snap = _latest_debt_date()
    debt_by = {r['client']: r['s'] for r in DebtFact.objects.filter(snapshot_date=snap)
               .exclude(client__in=excl).values('client').annotate(s=Sum('debt_total'))}
    over_limit = []
    for cl in Client.objects.exclude(credit_limit__isnull=True):
        dt = debt_by.get(cl.name, 0)
        if cl.credit_limit and dt > cl.credit_limit:
            over_limit.append({'client': cl.name, 'debt': dt, 'limit': cl.credit_limit,
                               'over': dt - cl.credit_limit})
    over_limit.sort(key=lambda x: -x['over'])

    # 4) SKU резко просел (последние 3 мес vs предыдущие 3, по деньгам)
    last_y = SkuFact.objects.aggregate(y=Max('year'))['y']
    sku_down = []
    if last_y:
        mns = sorted(set(SkuFact.objects.filter(year=last_y).values_list('month', flat=True)))
        recent, prior = mns[-3:], mns[-6:-3]
        if len(recent) >= 2 and prior:
            def sums(months):
                d = {}
                for r in (SkuFact.objects.filter(year=last_y, month__in=months, brand_type='own')
                          .values('sku_raw').annotate(s=Sum('amount'))):  # только свой бренд
                    if not str(r['sku_raw']).strip().startswith(_DOC_PREFIXES):
                        d[r['sku_raw']] = r['s'] or 0
                return d
            r3, p3 = sums(recent), sums(prior)
            for sku, pv in p3.items():
                rv = r3.get(sku, 0)
                if pv > 50000 and rv < pv * 0.6:
                    sku_down.append({'sku': sku, 'was': pv, 'now': rv,
                                     'drop': round((pv - rv) / pv * 100)})
            sku_down.sort(key=lambda x: -(x['was'] - x['now']))
    return {'silent': silent, 'debt_up': debt_up, 'over_limit': over_limit, 'sku_down': sku_down,
            'total': len(silent) + len(debt_up) + len(over_limit) + len(sku_down)}


def year_overview():
    """Сводная аналитика по годам: выручка, сезонность, топы, база клиентов, СТМ."""
    from collections import defaultdict
    excl = _excluded()
    years = sorted(set(SalesFact.objects.values_list('year', flat=True)))
    if not years:
        return {'years': []}
    sales_qs = SalesFact.objects.exclude(client__in=excl)

    # выручка по годам + рост
    tot = {y: 0 for y in years}
    for r in sales_qs.values('year').annotate(s=Sum('amount')):
        tot[r['year']] = r['s'] or 0
    revenue = []
    for i, y in enumerate(years):
        prev = tot[years[i - 1]] if i else 0
        growth = round((tot[y] - prev) / prev * 100) if i and prev else None
        revenue.append({'year': y, 'total': tot[y], 'growth': growth})

    # помесячно по годам (сезонность)
    monthly = {y: [0] * 12 for y in years}
    for r in sales_qs.values('year', 'month').annotate(s=Sum('amount')):
        monthly[r['year']][r['month'] - 1] = r['s'] or 0

    # топы × годы
    top_clients_m = _matrix(sales_qs, 'client', years, 8)
    top_managers_m = _matrix(sales_qs, 'manager', years, 8)
    top_sku_m = _matrix(SkuFact.objects.all(), 'sku_raw', years, 8, exclude_docs=True, norm=_sku_norm)

    # концентрация: доля топ-5 клиентов в каждом году
    conc = []
    for i, y in enumerate(years):
        yr_clients = sorted((sales_qs.filter(year=y).values('client')
                             .annotate(s=Sum('amount'))), key=lambda r: -(r['s'] or 0))
        top5 = sum((r['s'] or 0) for r in yr_clients[:5])
        conc.append(round(top5 / tot[y] * 100) if tot[y] else 0)

    # клиентская база: активные / новые / ушедшие
    client_years = defaultdict(set)
    for r in sales_qs.filter(amount__gt=0).values('client', 'year').distinct():
        client_years[r['client']].add(r['year'])
    first_year = {c: min(ys) for c, ys in client_years.items()}
    base = []
    for i, y in enumerate(years):
        active = {c for c, ys in client_years.items() if y in ys}
        new = {c for c in active if first_year[c] == y}
        prev_active = {c for c, ys in client_years.items() if years[i - 1] in ys} if i else set()
        lost = prev_active - active
        base.append({'year': y, 'active': len(active), 'new': len(new),
                     'lost': (len(lost) if i else None)})

    # СТМ vs свой бренд по годам (по типу карточки в SkuFact)
    stm = []
    for y in years:
        bt = {'own': 0, 'private_label': 0, 'non_product': 0}
        for r in SkuFact.objects.filter(year=y).values('brand_type').annotate(s=Sum('amount')):
            bt[r['brand_type']] = r['s'] or 0
        base_sum = bt['own'] + bt['private_label']
        stm.append({'year': y, 'own': bt['own'], 'stm': bt['private_label'],
                    'stm_share': round(bt['private_label'] / base_sum * 100) if base_sum else 0})

    return {'years': years, 'revenue': revenue, 'monthly': monthly, 'conc': conc,
            'top_clients': top_clients_m, 'top_managers': top_managers_m, 'top_sku': top_sku_m,
            'base': base, 'stm': stm, 'segments': segments_matrix(years)}


def yoy(year, prev, **f):
    f2 = {k: v for k, v in f.items() if k not in ('date_from', 'date_to')}
    return {'now': sales_summary(year, **f2)['by_month'], 'prev': sales_summary(prev, **f2)['by_month']}


def _short_money(n):
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}м'.replace('.0м', 'м')
    if n >= 1_000:
        return f'{round(n / 1000)}к'
    return str(int(n)) if n else ''


def payment_calendar(year, month):
    """Календарь ожидаемых оплат: по сроку оплаты из дебиторки раскладываем документы по дням."""
    import calendar as _cal
    from collections import defaultdict
    from .models import DebtLine
    by_date = defaultdict(lambda: {'amount': 0, 'count': 0, 'clients': defaultdict(int)})
    snap = _latest_debt_date()
    for r in DebtLine.objects.filter(snapshot_date=snap, due_date__isnull=False).values('due_date', 'client', 'debt_total'):
        c = by_date[r['due_date']]
        c['amount'] += r['debt_total']
        c['count'] += 1
        c['clients'][r['client']] += r['debt_total']
    month_days = [d for d in by_date if d.year == year and d.month == month]
    maxday = max((by_date[d]['amount'] for d in month_days), default=0) or 1
    today = date.today()
    weeks = []
    for week in _cal.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row = []
        for d in week:
            info = by_date.get(d)
            amount = info['amount'] if info else 0
            lvl = 0 if not amount else 1 + min(2, int(amount / maxday * 3 * 0.999))
            tip = None
            if amount:
                top = sorted(info['clients'].items(), key=lambda x: -x[1])[:3]
                names = ', '.join(c for c, _ in top)
                tip = (f"{d.strftime('%d.%m')} · {amount:,} ₽ · {info['count']} док · {names}"
                       .replace(',', ' '))
            row.append({'day': d.day, 'iso': d.strftime('%Y-%m-%d'), 'amount': amount,
                        'short': _short_money(amount), 'lvl': lvl, 'tip': tip,
                        'in_month': d.month == month, 'today': d == today})
        weeks.append(row)
    month_total = sum(by_date[d]['amount'] for d in month_days)
    return {'weeks': weeks, 'month_total': month_total, 'doc_count': sum(by_date[d]['count'] for d in month_days)}


def payment_forecast(weeks=8):
    """Прогноз поступлений по неделям вперёд (из сроков оплаты дебиторки, последний снимок)."""
    from datetime import timedelta
    from .models import DebtLine
    snap = _latest_debt_date()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(days=7 * weeks)
    buckets = [{'start': monday + timedelta(days=7 * i),
                'end': monday + timedelta(days=7 * i + 6), 'amount': 0} for i in range(weeks)]
    overdue = later = 0
    for l in (DebtLine.objects.filter(snapshot_date=snap, due_date__isnull=False)
              .values('due_date', 'debt_total')):
        d = l['due_date']
        if d < monday:
            overdue += l['debt_total']
        elif d >= end:
            later += l['debt_total']
        else:
            buckets[(d - monday).days // 7]['amount'] += l['debt_total']
    mx = max([b['amount'] for b in buckets] + [overdue], default=1) or 1
    for b in buckets:
        b['h'] = round(b['amount'] / mx * 100)
    return {'overdue': overdue, 'weeks': buckets, 'later': later, 'today': today,
            'total_8w': sum(b['amount'] for b in buckets)}


def payment_day(d):
    """Кто должен оплатить в конкретный день и за какие отгрузки (документы с этим сроком оплаты)."""
    from .models import DebtLine
    snap = _latest_debt_date()
    rows = list(DebtLine.objects.filter(snapshot_date=snap, due_date=d).order_by('-debt_total')
                .values('client', 'doc_no', 'ship_date', 'due_date',
                        'debt_total', 'debt_overdue', 'overdue_days'))
    smap = schet_map()
    for r in rows:
        r['light'] = 'red' if r['overdue_days'] > 30 else 'amb' if r['overdue_days'] > 0 else 'green'
        r['schet'] = smap.get(r['doc_no'], '')
    return rows


def plan_status(year=None, manager=None, date_from=None, date_to=None):
    """План/факт продаж по менеджерам и месяцам (план ведётся в админке).
    Учитывает фильтры: период (показываем планы месяцев внутри диапазона) и менеджер."""
    from .models import SalesPlan
    qs = SalesPlan.objects.all()
    if manager:
        qs = qs.filter(manager=manager)
    if date_from and date_to:                       # только планы месяцев внутри периода
        lo = date_from.year * 12 + date_from.month
        hi = date_to.year * 12 + date_to.month
        plans = [p for p in qs if lo <= p.year * 12 + p.month <= hi]
    elif year:
        plans = list(qs.filter(year=year))
    else:
        plans = list(qs)
    plans.sort(key=lambda p: (p.year, p.month, p.manager))
    out = []
    for p in plans:
        q = SalesFact.objects.filter(year=p.year, month=p.month).exclude(client__in=_excluded())
        if p.manager:
            q = q.filter(manager=p.manager)
        fact = q.aggregate(s=Sum('amount'))['s'] or 0
        out.append({'month': p.month, 'month_name': MONTHS[p.month - 1],
                    'manager': p.manager or 'все менеджеры', 'plan': p.amount, 'fact': fact,
                    'pct': round(fact / p.amount * 100) if p.amount else 0,
                    'remaining': max(p.amount - fact, 0)})
    return out


def clients_list(year):
    """Список клиентов: продажи по каждому году, текущий долг, канал. Возвращает (годы, строки)."""
    excl = _excluded()
    years = sorted(set(SalesFact.objects.values_list('year', flat=True)), reverse=True)
    sales_year = {}
    for r in SalesFact.objects.exclude(client__in=excl).values('client', 'year').annotate(s=Sum('amount')):
        sales_year[(r['client'], r['year'])] = r['s'] or 0
    debt = {}
    snap = _latest_debt_date()      # ТОЛЬКО последний снимок, иначе долг суммируется по всем снимкам
    for r in (DebtFact.objects.filter(snapshot_date=snap).exclude(client__in=excl)
              .values('client').annotate(t=Sum('debt_total'), o=Sum('debt_overdue'))):
        debt[r['client']] = (r['t'] or 0, r['o'] or 0)
    dir_rows = {c['name']: c for c in Client.objects.exclude(excluded=True)
                .values('name', 'channel', 'inn', 'synced_at')}
    names = set(k[0] for k in sales_year) | set(debt) | set(dir_rows)
    rows = []
    for n in names:
        info = dir_rows.get(n, {})
        by_year = [sales_year.get((n, y), 0) for y in years]
        rows.append({'name': n, 'by_year': by_year, 'sales': (by_year[0] if by_year else 0),
                     'debt': debt.get(n, (0, 0))[0], 'overdue': debt.get(n, (0, 0))[1],
                     'channel': info.get('channel', '') or '',
                     'inn': info.get('inn', '') or '', 'in_1c': bool(info.get('synced_at'))})
    rows.sort(key=lambda r: -r['sales'])
    return years, rows


def client_profile(client, year, prev):
    """Профиль клиента: продажи по месяцам (2 года), долг, расшифровка, история долга, справочные поля."""
    from .models import DebtClientSnapshot
    def months(yr):
        by = [0] * 12
        for r in (SalesFact.objects.filter(client=client, year=yr).values('month').annotate(s=Sum('amount'))):
            by[r['month'] - 1] = r['s'] or 0
        return by
    now, was = months(year), months(prev)
    d = debt_summary(client=client)
    row = d['debtors'][0] if d['debtors'] else None
    hist = list(DebtClientSnapshot.objects.filter(client=client).order_by('date')
                .values('date', 'debt_total', 'debt_overdue'))
    info = Client.objects.filter(name=client).first()
    from django.db.models import Count
    mgr = (SalesFact.objects.filter(client=client).exclude(manager='')
           .values('manager').annotate(c=Count('id')).order_by('-c').first())
    owner = mgr['manager'] if mgr else ''
    year_totals = [{'year': r['year'], 'total': r['s'] or 0} for r in
                   SalesFact.objects.filter(client=client).values('year')
                   .annotate(s=Sum('amount')).order_by('-year')]
    return {'owner_manager': owner, 'year_totals': year_totals,
            'now': now, 'prev': was, 'sales_total': sum(now), 'prev_total': sum(was),
            'debt': d, 'row': row, 'lines': debt_lines(client), 'hist': hist,
            'channel': info.get_channel_display() if info else '—',
            'credit_limit': info.credit_limit if info else None,
            'note': info.note if info else '',
            'over_limit': bool(info and info.credit_limit and row and row['debt_total'] > info.credit_limit),
            'info': info, 'synced_at': info.synced_at if info else None,
            'inn': info.inn if info else '', 'full_name': info.full_name if info else '',
            'phone': info.phone if info else '', 'contact': info.contact if info else '',
            'email': info.email if info else '', 'address': info.address if info else ''}


def filter_options(year):
    managers = sorted(set(SalesFact.objects.exclude(client__in=_excluded())
                          .exclude(manager='').values_list('manager', flat=True)))
    clients = sorted(set(SalesFact.objects.exclude(client__in=_excluded())
                         .values_list('client', flat=True)))
    channels = [c[0] for c in Client.CHANNELS]
    return {'managers': managers, 'clients': clients, 'channels': channels}


def _last3_sku_qty():
    """Продажи по SKU в штуках за последние 3 месяца (по SkuFact)."""
    from django.db.models import Max
    last = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not last:
        return {}, None
    months = sorted(set(SkuFact.objects.filter(year=last).values_list('month', flat=True)))
    m3 = months[-3:] if len(months) >= 3 else months
    qty = {}
    for r in (SkuFact.objects.filter(year=last, month__in=m3)
              .values('sku_raw').annotate(q=Sum('qty'))):
        qty[r['sku_raw']] = r['q'] or 0
    return qty, len(m3)


def packaging_status(series=None, used=None):
    """Статус упаковки: остаток, расход/мес по продажам, на сколько хватит."""
    from .models import PackagingItem
    sku_qty, nmon = _last3_sku_qty()
    nmon = nmon or 3
    rows = []
    for it in PackagingItem.objects.all():
        q3 = sku_qty.get(it.sku, 0)
        rate = q3 / nmon if q3 else 0
        is_used = it.is_active_manual if it.is_active_manual is not None else (rate > 0 or it.stock < 0)
        if series and it.series != series:
            continue
        if used == 'yes' and not is_used:
            continue
        if used == 'no' and is_used:
            continue
        deficit = it.stock < 0
        if deficit:
            months = None
            status = 'crit'
        else:
            months = (it.stock / rate) if rate > 0 else None
            status = ('crit' if months is not None and months < 1
                      else 'warn' if months is not None and months < 3
                      else 'ok' if months is not None else 'idle')
        rows.append({'upak': it.upak, 'series': it.series, 'stock': it.stock,
                     'rate': round(rate), 'months': months, 'status': status,
                     'used': is_used, 'deficit': deficit})
    # сортировка: дефицит → мало месяцев → остальное
    rows.sort(key=lambda r: (-1 if r['deficit'] else (r['months'] if r['months'] is not None else 9e9)))
    return rows


def packaging_series_list():
    from .models import PackagingItem
    return sorted(set(PackagingItem.objects.exclude(series='').values_list('series', flat=True)))
