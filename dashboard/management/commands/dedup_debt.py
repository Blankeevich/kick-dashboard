"""Разовая чистка уже загруженных строк дебиторки от фантомных дублей
(строка без номера, повторяющая строку с номером). Запуск: manage.py dedup_debt"""
from django.core.management.base import BaseCommand
from dashboard.models import DebtLine


class Command(BaseCommand):
    help = 'Убрать фантомные дубли реализаций в существующих снимках дебиторки'

    def handle(self, *a, **o):
        snaps = list(DebtLine.objects.values_list('snapshot_date', flat=True).distinct())
        removed = 0
        for snap in snaps:
            lines = list(DebtLine.objects.filter(snapshot_date=snap)
                         .values('id', 'client', 'ship_date', 'due_date', 'debt_total', 'doc_no'))
            numbered = {(l['client'], l['ship_date'], l['due_date'], l['debt_total'])
                        for l in lines if l['doc_no']}
            seen, to_del = set(), []
            for l in lines:
                k4 = (l['client'], l['ship_date'], l['due_date'], l['debt_total'])
                k5 = k4 + (l['doc_no'],)
                if (not l['doc_no'] and k4 in numbered) or k5 in seen:
                    to_del.append(l['id'])
                else:
                    seen.add(k5)
            if to_del:
                DebtLine.objects.filter(id__in=to_del).delete()
                removed += len(to_del)
            self.stdout.write(f'снимок {snap}: убрано {len(to_del)}, осталось {len(lines) - len(to_del)}')
        self.stdout.write(self.style.SUCCESS(f'Всего убрано дублей: {removed}'))
