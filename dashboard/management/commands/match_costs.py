"""Авто-привязка SKU к позициям себестоимости. Привязывает ТОЛЬКО свой бренд (однозначно);
СТМ-варианты (Самокат, ВкусВилл, ZERO≠Зелёная линия и т.п.) — вручную на странице привязки.
Запуск: manage.py match_costs           — донакинуть свой бренд
        manage.py match_costs --reset   — сначала очистить все привязки, потом заново"""
import re
from django.db.models import Sum, Max
from django.core.management.base import BaseCommand
from dashboard.models import CostItem, CostSku, SkuFact

_STOP = {'батончик', 'конфеты', 'конфета', 'шоколадные', 'кокосовые', 'кокосовая', 'в', 'с', 'и',
         'на', 'шок', 'шоколаде', 'месяцев', 'мес', '12', '6', 'kick', 'eat', 'me', 'шт', 'без',
         'сахара', 'для', 'из', 'по'}
# маркеры чужих брендов / СТМ-линий — такие SKU авто-привязывать НЕЛЬЗЯ
_STM = re.compile(r'самокат|вкусвилл|старс|stars|ригла|dermadrop|\btrue\b|зелен|fancy|zero|'
                  r'армен|молдов|дубай|арабск|черкесск|бионова|моспром|мищенко|фоксгрупп', re.I)


def _toks(s):
    s = re.sub(r'[^а-яёa-z0-9 ]', ' ', str(s).lower())
    return {w for w in s.split() if w not in _STOP and len(w) > 2}


def _cost_is_stm(name):
    return bool(_STM.search(name))


class Command(BaseCommand):
    help = 'Авто-привязать свой бренд к себестоимости (СТМ — вручную)'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='очистить все привязки перед матчем')

    def handle(self, *a, **o):
        if o.get('reset'):
            n = CostSku.objects.count()
            CostSku.objects.all().delete()
            CostItem.objects.exclude(sku='').update(sku='')
            self.stdout.write(f'Сброшено привязок: {n} + основные SKU')
        ly = SkuFact.objects.aggregate(y=Max('year'))['y']
        if not ly:
            self.stdout.write('Нет продаж по SKU'); return
        price, sku_tokens = {}, {}
        for r in (SkuFact.objects.filter(year=ly, qty__gt=0).values('sku_raw')
                  .annotate(a=Sum('amount'), q=Sum('qty'))):
            if r['q'] and not _STM.search(r['sku_raw']):      # только свой бренд
                price[r['sku_raw']] = r['a'] / r['q']
                sku_tokens[r['sku_raw']] = _toks(r['sku_raw'])
        attached = 0
        for it in CostItem.objects.all():
            if _cost_is_stm(it.name):        # СТМ-позиция себестоимости — не авто-матчим
                continue
            nt = _toks(it.name)
            have = {it.sku} if it.sku else set()
            best, bs = None, 0
            for sku, st in sku_tokens.items():
                o2 = len(nt & st)
                pnv = price[sku] / 1.22
                if o2 > bs and it.cost * 0.7 < pnv < it.cost * 4:
                    bs, best = o2, sku
            if best and bs >= 3 and best not in have:         # один лучший свой SKU
                if not it.sku:
                    it.sku = best
                    it.save(update_fields=['sku'])
                else:
                    CostSku.objects.get_or_create(cost=it, sku=best)
                attached += 1
        self.stdout.write(self.style.SUCCESS(
            f'Привязано (свой бренд): {attached}. С привязкой: '
            f'{CostItem.objects.exclude(sku="").count()} позиций. СТМ добавляй вручную.'))
