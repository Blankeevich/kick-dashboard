"""Авто-привязка СВОЕГО бренда к позициям себестоимости (по основам слов, окончания не мешают).
Только ДОБАВЛЯЕТ (ручные привязки не трогает). СТМ — вручную на странице привязки.
Запуск: manage.py match_costs"""
import re
from django.db.models import Sum, Max
from django.core.management.base import BaseCommand
from dashboard.models import CostItem, CostSku, SkuFact

_STOP = {'батончик', 'конфеты', 'конфета', 'шоколадные', 'кокосовые', 'кокосовая', 'в', 'с', 'и',
         'на', 'шок', 'шоколад', 'шоколаде', 'месяцев', 'мес', '12', '6', 'kick', 'eat', 'me',
         'шт', 'без', 'сахара', 'для', 'из', 'по', 'вкусе', 'вкусом', 'new'}
# чужие бренды / СТМ-линии — не авто-привязываем (различает только человек)
_STM = re.compile(r'самокат|вкусвилл|старс|stars|ригла|dermadrop|\btrue\b|зелен|fancy|zero|зеро|'
                  r'армен|молдов|дубай|арабск|черкесск|бионова|моспром|мищенко|фоксгрупп|бад', re.I)


def _stems(s):
    s = re.sub(r'[^а-яёa-z0-9 ]', ' ', str(s).lower())
    return {w[:5] for w in s.split() if w not in _STOP and len(w) > 2}


class Command(BaseCommand):
    help = 'Авто-привязать свой бренд к себестоимости (по основам слов, только добавляет)'

    def handle(self, *a, **o):
        ly = SkuFact.objects.aggregate(y=Max('year'))['y']
        if not ly:
            self.stdout.write('Нет продаж по SKU'); return
        price, sku_stems = {}, {}
        for r in (SkuFact.objects.filter(year=ly, qty__gt=0).values('sku_raw')
                  .annotate(a=Sum('amount'), q=Sum('qty'))):
            if r['q'] and not _STM.search(r['sku_raw']):      # только свой бренд
                price[r['sku_raw']] = r['a'] / r['q']
                sku_stems[r['sku_raw']] = _stems(r['sku_raw'])
        attached = 0
        for it in CostItem.objects.all():
            if _STM.search(it.name):
                continue
            nt = _stems(it.name)
            if len(nt) < 2:
                continue
            have = {it.sku} if it.sku else set()
            best, bs = None, 0
            for sku, st in sku_stems.items():
                inter = len(nt & st)
                # совпадение почти всех значимых слов позиции + правдоподобная цена
                if inter > bs and inter >= max(2, len(nt) - 1) and it.cost * 0.7 < price[sku] / 1.22 < it.cost * 4:
                    bs, best = inter, sku
            if best and best not in have:
                if not it.sku:
                    it.sku = best
                    it.save(update_fields=['sku'])
                else:
                    CostSku.objects.get_or_create(cost=it, sku=best)
                attached += 1
        self.stdout.write(self.style.SUCCESS(
            f'Привязано свой бренд: {attached}. С привязкой: '
            f'{CostItem.objects.exclude(sku="").count()} позиций. СТМ добавляй вручную.'))
