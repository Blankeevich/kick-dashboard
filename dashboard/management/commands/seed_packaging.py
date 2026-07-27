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
        # справочник целиком ведётся из seed-файла: чистим и грузим заново,
        # чтобы переименованные позиции не оставались дублями
        PackagingItem.objects.all().delete()
        for it in items:
            PackagingItem.objects.create(
                upak=it['upak'], sku=it['sku'], series=it['series'], stock=it['stock'])
        self.stdout.write(self.style.SUCCESS(f'Упаковка: загружено {len(items)} позиций'))
