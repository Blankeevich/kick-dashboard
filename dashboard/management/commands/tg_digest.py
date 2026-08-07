"""Утренняя сводка в Telegram: продажи, дебиторка, оплаты сегодня, лиды.
Запуск:   manage.py tg_digest
По расписанию: systemd timer в будни утром.
"""
from django.core.management.base import BaseCommand
from dashboard.telegram import digest_text
from dashboard.notify import send_telegram


class Command(BaseCommand):
    help = 'Отправляет утреннюю сводку в Telegram'

    def handle(self, *a, **o):
        ok, detail = send_telegram(digest_text())
        self.stdout.write((self.style.SUCCESS if ok else self.style.ERROR)('Сводка: ' + detail))
