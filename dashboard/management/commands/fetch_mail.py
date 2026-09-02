"""
Приёмник почты: читает Gmail/Mail.ru по IMAP, находит письма с вложениями xlsx/xls,
определяет тип отчёта по имени файла и грузит в базу тем же loader'ом, что и форма.

Настройки берутся из переменных окружения (не из кода, не в git):
  MAIL_HOST (по умолчанию imap.gmail.com), MAIL_USER, MAIL_PASS (пароль приложения)

Запуск:
  ./venv/bin/python manage.py fetch_mail                 # только непрочитанные (для таймера)
  ./venv/bin/python manage.py fetch_mail --all --force   # забрать ВСЁ из почты и перезалить
  ./venv/bin/python manage.py fetch_mail --days 14        # письма за последние 14 дней

При --all / --days берётся САМЫЙ СВЕЖИЙ файл каждого типа (номенклатура/контрагенты/дебиторка).
"""
import os
import io
import email
import imaplib
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from django.core.management.base import BaseCommand
from dashboard import loader

# соответствие «ключ в имени файла» → функция загрузки
ROUTES = [
    ('задолженност', loader.load_debt),
    ('номенклатур', loader.load_sales_sku),
    ('контрагент', loader.load_sales_client),
]


def _decode(s):
    if not s:
        return ''
    out = ''
    for txt, enc in decode_header(s):
        out += txt.decode(enc or 'utf-8', 'ignore') if isinstance(txt, bytes) else txt
    return out


class Command(BaseCommand):
    help = 'Забирает выгрузки 1С из почты и грузит в базу'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true',
                            help='все письма, а не только непрочитанные')
        parser.add_argument('--days', type=int, default=0,
                            help='письма за последние N дней (независимо от прочтения)')
        parser.add_argument('--force', action='store_true',
                            help='перезагружать, даже если такой файл уже грузился')

    def handle(self, *args, **opts):
        host = os.environ.get('MAIL_HOST', 'imap.gmail.com')
        user = os.environ.get('MAIL_USER')
        pw = os.environ.get('MAIL_PASS')
        if not user or not pw:
            self.stderr.write('MAIL_USER / MAIL_PASS не заданы в окружении')
            return

        self.stdout.write(f'Подключаюсь к {host} как {user}...')
        M = imaplib.IMAP4_SSL(host)
        M.login(user, pw)
        M.select('INBOX')

        if opts['days']:
            since = (datetime.now() - timedelta(days=opts['days'])).strftime('%d-%b-%Y')
            typ, data = M.search(None, 'SINCE', since)
            self.stdout.write(f'Письма с {since}')
        elif opts['all']:
            typ, data = M.search(None, 'ALL')
            self.stdout.write('Все письма в ящике')
        else:
            typ, data = M.search(None, 'UNSEEN')
            self.stdout.write('Только непрочитанные')

        ids = data[0].split()
        self.stdout.write(f'Найдено писем: {len(ids)}')

        # собираем все подходящие вложения с датой письма
        found = []  # (ts, num, fname, payload, loader_fn, key)
        for num in ids:
            typ, msgdata = M.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(msgdata[0][1])
            try:
                ts = parsedate_to_datetime(msg['Date']).timestamp()
            except Exception:
                ts = 0
            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                fname = _decode(part.get_filename())
                if not fname or not fname.lower().endswith(('.xlsx', '.xls')):
                    continue
                low = fname.lower()
                hit = next(((key, f) for key, f in ROUTES if key in low), None)
                if not hit:
                    continue
                key, fn = hit
                found.append((ts, num, fname, part.get_payload(decode=True), fn, key))

        # на каждый тип отчёта берём самый свежий файл
        latest = {}
        for rec in found:
            key = rec[5]
            if key not in latest or rec[0] > latest[key][0]:
                latest[key] = rec

        if not latest:
            self.stdout.write('Подходящих вложений (номенклатура/контрагенты/дебиторка) не найдено')
            M.logout()
            return

        loaded, skipped = 0, 0
        for key, (ts, num, fname, payload, fn, _k) in latest.items():
            bio = io.BytesIO(payload)
            bio.name = fname
            try:
                r = fn(bio, fname, None, force=opts['force'])
                if r.get('skipped'):
                    self.stdout.write(f'  {fname}: пропущено — {r["reason"]}')
                    skipped += 1
                else:
                    rows = r.get('rows', 0)
                    total = r.get('total', 0)
                    self.stdout.write(f'  {fname}: загружено {rows} строк, сумма {total:,} ₽')
                    loaded += 1
                M.store(num, '+FLAGS', '\\Seen')
            except Exception as e:
                self.stderr.write(f'  ОШИБКА {fname}: {e}')

        M.logout()
        self.stdout.write(self.style.SUCCESS(f'Готово. Загружено: {loaded}, пропущено: {skipped}'))
