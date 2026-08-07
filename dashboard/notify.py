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
import urllib.error
from email.message import EmailMessage


def send_yadisk(filename, data):
    """Загружает файл на Яндекс.Диск по WebDAV (надёжно с российского VPS). (ok, detail).
    Нужен YADISK_USER (логин Яндекса) и YADISK_PASS (пароль приложения для WebDAV)."""
    import base64
    user = os.environ.get('YADISK_USER')
    pwd = os.environ.get('YADISK_PASS')
    if not (user and pwd):
        return False, 'нет YADISK_USER/YADISK_PASS'
    folder = os.environ.get('YADISK_DIR', 'kick_backups').strip('/')
    auth = 'Basic ' + base64.b64encode(('%s:%s' % (user, pwd)).encode()).decode()
    # создаём папку (MKCOL) — если уже есть, вернётся 405, это ок
    try:
        mk = urllib.request.Request('https://webdav.yandex.ru/%s' % folder, method='MKCOL')
        mk.add_header('Authorization', auth)
        try:
            urllib.request.urlopen(mk, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code not in (405, 409, 201):
                pass
    except Exception:
        pass
    url = 'https://webdav.yandex.ru/%s/%s' % (folder, filename)
    try:
        req = urllib.request.Request(url, data=data, method='PUT')
        req.add_header('Authorization', auth)
        urllib.request.urlopen(req, timeout=300)
        return True, 'загружено на Яндекс.Диск (%s/%s)' % (folder, filename)
    except Exception as e:
        return False, 'Яндекс.Диск ошибка: %s' % e


def _tg_base():
    # можно пустить через прокси (Cloudflare Worker), если api.telegram.org недоступен с РФ-хостинга
    return os.environ.get('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')


def tg_open(req_or_url, timeout=60, tries=4):
    """urlopen с ретраями + нормальный User-Agent (Cloudflare режет дефолтный Python-urllib → 403)."""
    import time
    req = urllib.request.Request(req_or_url) if isinstance(req_or_url, str) else req_or_url
    if not req.has_header('User-agent'):
        req.add_header('User-Agent', 'Mozilla/5.0 (KICK-bot)')
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def send_telegram(text, document=None, filename='file', chat_id=None):
    """Шлёт в Telegram текст, а если задан document (bytes) — файл. (ok, detail).
    chat_id переопределяет TELEGRAM_CHAT_ID (нужно для ответов боту тому, кто написал)."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = chat_id or os.environ.get('TELEGRAM_CHAT_ID')
    if not (token and chat):
        return False, 'нет TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID'
    base = _tg_base()
    try:
        if document is None:
            data = urllib.parse.urlencode({'chat_id': chat, 'text': text[:4000],
                                           'parse_mode': 'HTML', 'disable_web_page_preview': 'true'}).encode()
            tg_open(urllib.request.Request('%s/bot%s/sendMessage' % (base, token), data=data), timeout=60)
        else:
            boundary = '----kick%d' % int(time.time())

            def field(name, val):
                return ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                        % (boundary, name, val)).encode()
            body = field('chat_id', chat) + field('caption', text[:1000])
            body += ('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
                     'Content-Type: application/octet-stream\r\n\r\n' % (boundary, filename)).encode()
            body += document + b'\r\n' + ('--%s--\r\n' % boundary).encode()
            req = urllib.request.Request('%s/bot%s/sendDocument' % (base, token), data=body)
            req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
            tg_open(req, timeout=180)
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
