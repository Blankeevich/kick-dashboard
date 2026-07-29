"""Завести в справочник «Клиенты» всех контрагентов, которые есть в продажах,
ровно под их именем из продаж (чтобы их можно было выбирать в группах и сшивать).
Запуск: manage.py sync_clients"""
from django.core.management.base import BaseCommand
from dashboard.models import SalesFact, Client


class Command(BaseCommand):
    help = 'Создать записи Client для всех покупателей из продаж'

    def handle(self, *a, **o):
        have = set(Client.objects.values_list('name', flat=True))
        sales = set(SalesFact.objects.exclude(client='').values_list('client', flat=True).distinct())
        new = [n for n in sales if n and n not in have]
        if new:
            Client.objects.bulk_create([Client(name=n) for n in new], ignore_conflicts=True)
        self.stdout.write(self.style.SUCCESS(
            f'Добавлено клиентов из продаж: {len(new)}. Всего в справочнике: {Client.objects.count()}'))
