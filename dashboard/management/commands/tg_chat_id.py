"""Показать chat_id для Telegram-уведомлений.
1) Создай бота у @BotFather, положи токен в .env: TELEGRAM_BOT_TOKEN=...
2) Напиши своему боту любое сообщение (или добавь его в группу и напиши там).
3) Запусти:  set -a && . ./.env && set +a && manage.py tg_chat_id
   Команда покажет chat_id — впиши его в .env: TELEGRAM_CHAT_ID=...
"""
import os
import json
import urllib.request
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Показывает chat_id из свежих сообщений боту (для настройки уведомлений)'

    def handle(self, *a, **o):
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:
            self.stdout.write(self.style.ERROR('Нет TELEGRAM_BOT_TOKEN в окружении (.env)'))
            return
        base = os.environ.get('TELEGRAM_API_BASE', 'https://api.telegram.org').rstrip('/')
        from dashboard.notify import tg_open
        try:
            raw = tg_open('%s/bot%s/getUpdates' % (base, token), timeout=30).read()
            data = json.loads(raw)
        except Exception as e:
            self.stdout.write(self.style.ERROR('Ошибка запроса: %s' % e))
            return
        seen = {}
        for u in data.get('result', []):
            msg = u.get('message') or u.get('channel_post') or {}
            chat = msg.get('chat') or {}
            if chat.get('id'):
                seen[chat['id']] = chat.get('title') or chat.get('username') or chat.get('first_name') or ''
        if not seen:
            self.stdout.write(self.style.WARNING(
                'Сообщений нет. Напиши боту любое сообщение в Telegram и запусти команду снова.'))
            return
        self.stdout.write(self.style.SUCCESS('Найдены чаты (впиши id в .env как TELEGRAM_CHAT_ID):'))
        for cid, name in seen.items():
            self.stdout.write('  chat_id = %s   (%s)' % (cid, name))
