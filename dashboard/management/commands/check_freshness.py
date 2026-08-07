"""Проверка свежести данных. Если последняя загрузка продаж/дебиторки старше порога —
шлёт письмо-алерт (чтобы не работать по устаревшим цифрам, не заметив сбой рассылки 1С).

Запуск:   manage.py check_freshness            # порог 26 часов
          manage.py check_freshness --hours 40
По расписанию: systemd timer раз в день утром (после времени рассылки 1С).
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from dashboard.models import Upload
from dashboard.notify import send_email, send_telegram


class Command(BaseCommand):
    help = 'Алерт, если данные давно не обновлялись'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=26)

    def handle(self, *a, **o):
        limit = o['hours']
        now = timezone.now()
        stale = []
        checks = [('sales_client', 'Продажи'), ('debt', 'Дебиторка')]
        for kind, label in checks:
            last = Upload.objects.filter(kind=kind).order_by('-uploaded_at').first()
            if last is None:
                stale.append(f'{label}: не загружалось НИ РАЗУ')
            else:
                age = now - last.uploaded_at
                if age > timedelta(hours=limit):
                    h = int(age.total_seconds() // 3600)
                    stale.append(f'{label}: последняя загрузка {last.uploaded_at:%d.%m.%Y %H:%M} '
                                 f'({h} ч назад, файл «{last.filename}»)')
        if not stale:
            self.stdout.write(self.style.SUCCESS('Данные свежие, алерт не нужен'))
            return
        body = ('Внимание: данные в дашборде KICK давно не обновлялись — возможно, сбой рассылки 1С '
                'или письмо не пришло/прочитано вручную.\n\n' + '\n'.join('• ' + s for s in stale) +
                '\n\nПроверь рассылку отчётов в 1С и приёмник почты. https://erp.pkfoodrev.ru')
        ok, detail = send_telegram('⚠️ KICK: данные не обновились\n\n' + body)
        if not ok:
            ok, detail = send_email('⚠️ KICK: данные не обновились', body)
        if ok:
            self.stdout.write(self.style.WARNING('Алерт отправлен: ' + detail))
        else:
            self.stdout.write(self.style.ERROR('Не удалось отправить алерт: ' + detail))
