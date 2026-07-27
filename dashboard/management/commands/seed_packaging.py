"""Загружает справочник упаковки из dashboard/data/packaging_seed.json.
Обновляет остатки существующих, создаёт новые. Запуск: manage.py seed_packaging"""
import json, os
import dashboard
from django.core.management.base import BaseCommand
from dashboard.models import PackagingItem


class Command(BaseCommand):
    help = 'Загрузить/обновить справочник упаковки из seed-файла'

    def handle(self, *a, **o):
        path = os.path.join(os.path.dirname(dashboard.__file__), 'data', 'packaging_seed.json')
        items = json.load(open(path, encoding='utf-8'))
        created = updated = 0
        for it in items:
            obj, is_new = PackagingItem.objects.update_or_create(
                upak=it['upak'],
                defaults={'sku': it['sku'], 'series': it['series'], 'stock': it['stock']})
            created += is_new
            updated += not is_new
        self.stdout.write(self.style.SUCCESS(f'Упаковка: создано {created}, обновлено {updated}'))
