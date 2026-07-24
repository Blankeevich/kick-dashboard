"""
Приёмник почты: раз в сутки читает Gmail по IMAP, находит письма с вложениями-xlsx,
определяет тип отчёта по имени файла и грузит в базу через тот же loader, что и форма.

Настройки берутся из переменных окружения (не из кода, не в git):
  MAIL_HOST (по умолчанию imap.gmail.com), MAIL_USER, MAIL_PASS (пароль приложения Gmail)

Запуск вручную:  ./venv/bin/python manage.py fetch_mail
По расписанию:   systemd timer (ежедневно ночью)
"""
import os
import io
import email
import imaplib
from email.header import decode_header
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
    parts = decode_header(s)
    out = ''
    for txt, enc in parts:
        out += txt.decode(enc or 'utf-8', 'ignore') if isinstance(txt, bytes) else txt
    return out


class Command(BaseCommand):
    help = 'Забирает выгрузки 1С из почты и грузит в базу'

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
        # непрочитанные письма с вложениями
        typ, data = M.search(None, 'UNSEEN')
        ids = data[0].split()
        self.stdout.write(f'Непрочитанных писем: {len(ids)}')

        loaded, skipped = 0, 0
        for num in ids:
            typ, msgdata = M.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(msgdata[0][1])
            handled_any = False
            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                fname = _decode(part.get_filename())
                if not fname or not fname.lower().endswith(('.xlsx', '.xls')):
                    continue
                low = fname.lower()
                fn = next((f for key, f in ROUTES if key in low), None)
                if not fn:
                    self.stdout.write(f'  пропуск (неизвестный файл): {fname}')
                    continue
                payload = part.get_payload(decode=True)
                bio = io.BytesIO(payload)
                bio.name = fname
                try:
                    r = fn(bio, fname, None)
                    if r.get('skipped'):
                        self.stdout.write(f'  {fname}: пропущено — {r["reason"]}')
                        skipped += 1
                    else:
                        self.stdout.write(f'  {fname}: загружено {r["rows"]} строк, сумма {r["total"]:,} ₽')
                        loaded += 1
                    handled_any = True
                except Exception as e:
                    self.stderr.write(f'  ОШИБКА {fname}: {e}')
            # помечаем письмо прочитанным только если обработали (иначе оставим на следующий раз)
            if handled_any:
                M.store(num, '+FLAGS', '\\Seen')

        M.logout()
        self.stdout.write(self.style.SUCCESS(f'Готово. Загружено файлов: {loaded}, пропущено: {skipped}'))
