"""Загрузка справочника себестоимости из dashboard/data/cost_seed.json.
Обновляет линейку и себестоимость, привязку SKU ставит только если она ещё пустая
(ручные правки менеджера не затираются). Запуск: manage.py seed_costs"""
import json
import os
from datetime import date
import dashboard
from django.core.management.base import BaseCommand
from dashboard.models import CostItem


class Command(BaseCommand):
    help = 'Загрузить/обновить справочник себестоимости из seed-файла'

    def handle(self, *a, **o):
        path = os.path.join(os.path.dirname(dashboard.__file__), 'data', 'cost_seed.json')
        items = json.load(open(path, encoding='utf-8'))
        today = date.today()
        created = updated = 0
        for it in items:
            obj = CostItem.objects.filter(name=it['name']).first()
            if obj is None:
                obj = CostItem(name=it['name'], sku=it.get('sku', ''))
                created += 1
            else:
                updated += 1
            obj.line = it.get('line', '')
            obj.cost = it['cost']
            if not obj.sku and it.get('sku'):
                obj.sku = it['sku']
            obj.updated_at = today
            obj.save()
        self.stdout.write(self.style.SUCCESS(f'Себестоимость: создано {created}, обновлено {updated}'))
