"""Отправка алертов и бэкапов. Два канала:
  1) Telegram (по HTTPS — работает на Timeweb, в отличие от SMTP): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  2) SMTP mail.ru (запасной; на Timeweb исходящий SMTP часто заблокирован): MAIL_USER, MAIL_PASS,
     MAIL_SMTP_HOST (smtp.mail.ru), MAIL_SMTP_PORT (465)
Ничего не хранится в коде/гите.
"""
import os
import time
import ssl
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage


def send_telegram(text, document=None, filename='file'):
    """Шлёт в Telegram текст, а если задан document (bytes) — файл. (ok, detail)."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not (token and chat):
        return False, 'нет TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID'
    try:
        if document is None:
            data = urllib.parse.urlencode({'chat_id': chat, 'text': text[:4000]}).encode()
            urllib.request.urlopen('https://api.telegram.org/bot%s/sendMessage' % token, data=data, timeout=60)
        else:
            boundary = '----kick%d' % int(time.time())

            def field(name, val):
                return ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                        % (boundary, name, val)).encode()
            body = field('chat_id', chat) + field('caption', text[:1000])
            body += ('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
                     'Content-Type: application/octet-stream\r\n\r\n' % (boundary, filename)).encode()
            body += document + b'\r\n' + ('--%s--\r\n' % boundary).encode()
            req = urllib.request.Request('https://api.telegram.org/bot%s/sendDocument' % token, data=body)
            req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
            urllib.request.urlopen(req, timeout=180)
        return True, 'отправлено в Telegram'
    except Exception as e:
        return False, 'Telegram ошибка: %s' % e


def send_email(subject, body, to=None, attachments=None):
    """attachments = список (filename, bytes). Возвращает (ok, detail)."""
    user = os.environ.get('MAIL_USER')
    pwd = os.environ.get('MAIL_PASS')
    to = to or os.environ.get('ALERT_EMAIL') or user
    if not (user and pwd and to):
        return False, 'нет MAIL_USER/MAIL_PASS/ALERT_EMAIL в окружении'
    host = os.environ.get('MAIL_SMTP_HOST', 'smtp.mail.ru')
    port = int(os.environ.get('MAIL_SMTP_PORT', '465'))
    msg = EmailMessage()
    msg['From'] = user
    msg['To'] = to
    msg['Subject'] = subject
    msg.set_content(body)
    for fn, data in (attachments or []):
        msg.add_attachment(data, maintype='application', subtype='octet-stream', filename=fn)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, pwd)
            s.send_message(msg)
        return True, 'отправлено на %s' % to
    except Exception as e:
        return False, 'ошибка SMTP: %s' % e
