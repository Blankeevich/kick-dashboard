"""Авто-привязка SKU к позициям себестоимости по совпадению рецепта (свой бренд + СТМ-варианты).
Осторожно: привязывает только уверенные совпадения с правдоподобной ценой. Запуск: manage.py match_costs"""
import re
from django.db.models import Sum, Max
from django.core.management.base import BaseCommand
from dashboard.models import CostItem, CostSku, SkuFact

_STOP = {'батончик', 'конфеты', 'конфета', 'шоколадные', 'кокосовые', 'кокосовая', 'в', 'с', 'и',
         'на', 'шок', 'шоколаде', 'месяцев', 'мес', '12', '6', 'kick', 'eat', 'me', 'шт', 'без',
         'сахара', 'для', 'из', 'по'}


def _toks(s):
    s = re.sub(r'[^а-яёa-z0-9 ]', ' ', str(s).lower())
    return {w for w in s.split() if w not in _STOP and len(w) > 2}


class Command(BaseCommand):
    help = 'Авто-привязать SKU (свой + СТМ) к себестоимости по совпадению названия'

    def handle(self, *a, **o):
        ly = SkuFact.objects.aggregate(y=Max('year'))['y']
        if not ly:
            self.stdout.write('Нет продаж по SKU'); return
        price, sku_tokens = {}, {}
        for r in (SkuFact.objects.filter(year=ly, qty__gt=0).values('sku_raw')
                  .annotate(a=Sum('amount'), q=Sum('qty'))):
            if r['q']:
                price[r['sku_raw']] = r['a'] / r['q']
                sku_tokens[r['sku_raw']] = _toks(r['sku_raw'])
        attached = 0
        for it in CostItem.objects.all():
            nt = _toks(it.name)
            for sku, st in sku_tokens.items():
                overlap = len(nt & st)
                pnv = price[sku] / 1.22
                # уверенное совпадение рецепта + правдоподобная цена (не набор/шоу-бокс)
                if overlap >= 3 and it.cost * 0.7 < pnv < it.cost * 4:
                    _, is_new = CostSku.objects.get_or_create(cost=it, sku=sku)
                    attached += is_new
        self.stdout.write(self.style.SUCCESS(
            f'Привязано SKU: {attached}. Позиций с привязкой: '
            f'{CostItem.objects.filter(skus__isnull=False).distinct().count()} из {CostItem.objects.count()}'))
