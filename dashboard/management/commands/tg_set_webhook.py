"""Регистрирует вебхук бота в Telegram, чтобы команды доходили до сайта.
Нужны в окружении: TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, SITE_URL (напр. https://erp.pkfoodrev.ru),
опц. TELEGRAM_API_BASE (прокси).
Запуск:   manage.py tg_set_webhook           # установить
          manage.py tg_set_webhook --delete  # снять (вернуться к getUpdates)
"""
import os
import json
import urllib.parse
import urllib.request
from django.core.management.base import BaseCommand
from dashboard.notify import tg_open


class Command(BaseCommand):
    help = 'Устанавливает/снимает Telegram webhook'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true')

    def handle(self, *a, **o):
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        base = os.environ.get('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')
        if not token:
            self.stdout.write(self.style.ERROR('Нет TELEGRAM_BOT_TOKEN')); return
        if o['delete']:
            r = tg_open('%s/bot%s/deleteWebhook' % (base, token), timeout=30).read()
            self.stdout.write('deleteWebhook: ' + r.decode('utf-8', 'ignore')); return
        secret = os.environ.get('TELEGRAM_WEBHOOK_SECRET')
        site = (os.environ.get('SITE_URL') or 'https://erp.pkfoodrev.ru').rstrip('/')
        if not secret:
            self.stdout.write(self.style.ERROR('Нет TELEGRAM_WEBHOOK_SECRET в .env')); return
        hook = '%s/tg/%s/webhook/' % (site, secret)
        url = '%s/bot%s/setWebhook?%s' % (base, token, urllib.parse.urlencode({'url': hook}))
        r = tg_open(url, timeout=30).read().decode('utf-8', 'ignore')
        self.stdout.write(self.style.SUCCESS('setWebhook → %s' % hook))
        self.stdout.write('ответ Telegram: ' + r)
        # меню команд (по кнопке «/») — Telegram допускает только английские имена
        cmds = [
            {'command': 'digest', 'description': 'Полная сводка'},
            {'command': 'sales', 'description': 'Продажи + топ клиентов'},
            {'command': 'debt', 'description': 'Дебиторка + топ должников'},
            {'command': 'overdue', 'description': 'Что просрочено'},
            {'command': 'payments', 'description': 'Кто платит сегодня'},
            {'command': 'leads', 'description': 'Воронка лидов'},
        ]
        data = urllib.parse.urlencode({'commands': json.dumps(cmds, ensure_ascii=False)}).encode()
        req = urllib.request.Request('%s/bot%s/setMyCommands' % (base, token), data=data)
        rc = tg_open(req, timeout=30).read().decode('utf-8', 'ignore')
        self.stdout.write('setMyCommands: ' + rc)
