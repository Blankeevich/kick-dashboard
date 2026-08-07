"""Тонкий клиент к HTTP-сервису 1С: тянет PDF документа по номеру (счёт/реализация).
Настройка через окружение (секреты не в коде):
  ONEC_SCHET_URL  — шаблон URL для счёта, с плейсхолдером {no}
  ONEC_REAL_URL   — шаблон URL для реализации, с {no}
  ONEC_USER, ONEC_PASS — basic-auth к веб-сервису 1С (обычно так)
  ONEC_TIMEOUT    — таймаут, сек (по умолч. 30)

Пример шаблона:
  ONEC_SCHET_URL=https://1c.example.ru/base/hs/kick/schet?number={no}
"""
import os
import base64
import urllib.parse
import urllib.request


def _tmpl(kind):
    return os.environ.get('ONEC_SCHET_URL' if kind == 'schet' else 'ONEC_REAL_URL')


def ready(kind=None):
    """Настроен ли 1С-сервис (хотя бы для одного вида документа)."""
    if kind:
        return bool(_tmpl(kind))
    return bool(_tmpl('schet') or _tmpl('real'))


def fetch_doc(kind, number):
    """Возвращает (data_bytes, content_type) или (None, error_text)."""
    tmpl = _tmpl(kind)
    if not tmpl:
        return None, '1С-сервис не настроен (нет ONEC_%s_URL)' % ('SCHET' if kind == 'schet' else 'REAL')
    url = tmpl.replace('{no}', urllib.parse.quote(str(number)))
    req = urllib.request.Request(url)
    user = os.environ.get('ONEC_USER')
    pwd = os.environ.get('ONEC_PASS')
    if user and pwd:
        req.add_header('Authorization', 'Basic ' + base64.b64encode(('%s:%s' % (user, pwd)).encode()).decode())
    req.add_header('User-Agent', 'KICK-dashboard')
    try:
        resp = urllib.request.urlopen(req, timeout=int(os.environ.get('ONEC_TIMEOUT', '30')))
        data = resp.read()
        ct = resp.headers.get('Content-Type', 'application/pdf')
        if not data:
            return None, '1С вернула пустой ответ (документ не найден?)'
        return (data, ct), None
    except Exception as e:
        return None, '1С недоступна или документ не найден: %s' % e
