"""Опросчик Telegram (long polling через прокси). Нужен потому, что входящий вебхук
не доходит до РФ-сервера (Telegram → RU режется). Здесь весь трафик исходящий.

Крутится постоянно как systemd-сервис (Restart=always).
Запуск вручную: set -a && . ./.env && set +a && manage.py tg_poll
"""
import os
import json
import time
import urllib.parse
from django.core.management.base import BaseCommand
from dashboard.notify import tg_open
from dashboard.telegram import handle_update


class Command(BaseCommand):
    help = 'Long-polling бота (ловит команды через прокси)'

    def handle(self, *a, **o):
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        base = os.environ.get('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')
        if not token:
            self.stdout.write(self.style.ERROR('Нет TELEGRAM_BOT_TOKEN')); return
        # вебхук и getUpdates взаимоисключающи — снимаем вебхук
        try:
            tg_open('%s/bot%s/deleteWebhook' % (base, token), timeout=30)
        except Exception:
            pass
        self.stdout.write(self.style.SUCCESS('tg_poll запущен, слушаю команды…'))
        offset = None
        while True:
            params = {'timeout': 25}
            if offset is not None:
                params['offset'] = offset
            try:
                url = '%s/bot%s/getUpdates?%s' % (base, token, urllib.parse.urlencode(params))
                resp = tg_open(url, timeout=40, tries=2)
                data = json.loads(resp.read().decode('utf-8', 'ignore'))
            except Exception:
                time.sleep(3)
                continue
            for u in data.get('result', []):
                offset = u['update_id'] + 1
                try:
                    handle_update(u)
                except Exception as e:
                    self.stdout.write(self.style.WARNING('ошибка обработки: %s' % e))
