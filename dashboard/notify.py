"""Отправка писем (алерты, бэкапы) через SMTP mail.ru.
Креды берутся из окружения (те же, что у приёмника почты):
  MAIL_USER, MAIL_PASS · опц. MAIL_SMTP_HOST (по умолч. smtp.mail.ru), MAIL_SMTP_PORT (465)
Ничего не хранится в коде/гите.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


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
