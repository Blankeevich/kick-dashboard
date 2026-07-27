"""
Витрины: агрегация фактов из базы в цифры для дашборда.
Фильтры: год ИЛИ произвольный период (date_from/date_to), менеджер, канал, контрагент.
"""
from datetime import date
from django.db.models import Sum
from .models import SalesFact, SkuFact, DebtFact, Client

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def _excluded():
    return set(Client.objects.filter(excluded=True).values_list('name', flat=True))


def _clients_in_channel(channel):
    return set(Client.objects.filter(channel=channel).values_list('name', flat=True))


def sales_qs(year=None, manager=None, channel=None, client=None, date_from=None, date_to=None):
    """Queryset продаж. Если задан период (date_from/date_to) — фильтр по дате документа,
    иначе по году."""
    qs = SalesFact.objects.exclude(client__in=_excluded())
    if date_from and date_to:
        qs = qs.filter(doc_date__range=[date_from, date_to])
    elif year:
        qs = qs.filter(year=year)
    if manager:
        qs = qs.filter(manager=manager)
    if client:
        qs = qs.filter(client=client)
    if channel:
        qs = qs.filter(client__in=_clients_in_channel(channel))
    return qs


def sales_summary(year=None, **f):
    qs = sales_qs(year, **f)
    total = qs.aggregate(s=Sum('amount'))['s'] or 0
    returns = qs.filter(amount__lt=0).aggregate(s=Sum('amount'))['s'] or 0
    by_month = [0] * 12
    for row in qs.values('month').annotate(s=Sum('amount')):
        by_month[row['month'] - 1] = row['s'] or 0
    return {'total': total, 'returns': returns, 'by_month': by_month}


def all_clients(year=None, **f):
    qs = sales_qs(year, **f)
    total = qs.aggregate(s=Sum('amount'))['s'] or 1
    rows = qs.values('client').annotate(s=Sum('amount')).order_by('-s')
    return [{'name': r['client'], 'amount': r['s'], 'share': round(r['s'] / total * 100, 1)} for r in rows]


def top_clients(year=None, limit=5, **f):
    return all_clients(year, **f)[:limit]


def by_manager(year=None, **f):
    f2 = {k: v for k, v in f.items() if k != 'manager'}
    qs = sales_qs(year, **f2)
    rows = qs.values('manager').annotate(s=Sum('amount')).order_by('-s')
    total = sum(r['s'] for r in rows) or 1
    out = []
    for r in rows:
        clients = qs.filter(manager=r['manager']).values('client').distinct().count()
        out.append({'manager': r['manager'] or '—', 'amount': r['s'],
                    'share': round(r['s'] / total * 100, 1), 'clients': clients})
    return out


def sales_by_day(year=None, month=None, **f):
    qs = sales_qs(year, **f).filter(doc_date__isnull=False, amount__gt=0)
    # при заданном периоде — по всем дням периода
    if f.get('date_from') and f.get('date_to'):
        rows = qs.values('doc_date').annotate(s=Sum('amount')).order_by('doc_date')
        return {'month': None, 'month_name': 'период',
                'days': [{'day': r['doc_date'].strftime('%d.%m'), 'amount': r['s']} for r in rows]}
    if month is None:
        last = qs.order_by('-doc_date').values_list('doc_date', flat=True).first()
        if not last:
            return {'month': None, 'month_name': '', 'days': []}
        month = last.month
    rows = (qs.filter(doc_date__month=month).values('doc_date')
            .annotate(s=Sum('amount')).order_by('doc_date'))
    return {'month': month, 'month_name': MONTHS[month - 1],
            'days': [{'day': r['doc_date'].day, 'amount': r['s']} for r in rows]}


# строки-документы, которые не должны попадать в список SKU
_DOC_PREFIXES = ('Реализация', 'Корректировка', 'Отчет комисс', 'Отчёт комисс', 'Операция', 'Возврат', 'Списание')


def top_sku(year=None, limit=8):
    qs = SkuFact.objects.filter(year=year) if year else SkuFact.objects.all()
    rows = qs.values('sku_raw').annotate(s=Sum('amount'), q=Sum('qty')).order_by('-s')
    out = []
    for r in rows:
        if str(r['sku_raw']).strip().startswith(_DOC_PREFIXES):
            continue  # это строка-документ, не товар
        out.append({'name': r['sku_raw'], 'amount': r['s'], 'qty': int(r['q'] or 0),
                    'price': round(r['s'] / r['q']) if r['q'] else 0})
        if len(out) >= limit:
            break
    return out


def debt_summary(manager=None, client=None, only_overdue=False, min_amount=1000, order='-debt_total'):
    qs = DebtFact.objects.exclude(client__in=_excluded()).filter(debt_total__gte=min_amount)
    if manager:
        qs = qs.filter(manager=manager)
    if client:
        qs = qs.filter(client=client)
    if only_overdue:
        qs = qs.filter(debt_overdue__gt=0)
    total = qs.aggregate(s=Sum('debt_total'))['s'] or 0
    overdue = qs.aggregate(s=Sum('debt_overdue'))['s'] or 0
    allowed = {'-debt_total', 'debt_total', '-overdue_days', 'overdue_days', 'due_date', '-due_date', 'client'}
    if order not in allowed:
        order = '-debt_total'
    debtors = list(qs.order_by(order).values(
        'client', 'manager', 'debt_total', 'debt_overdue', 'overdue_days', 'due_date'))
    return {'total': total, 'overdue': overdue,
            'share': round(overdue / total * 100, 1) if total else 0,
            'count': qs.count(), 'debtors': debtors}


def client_sales(client, limit=100):
    """Реализации клиента (для расшифровки по клику из дебиторки).
    Приблизительно: все продажи клиента с датами. Точная привязка к долгу —
    после выгрузки расшифровки дебиторки из 1С."""
    qs = (SalesFact.objects.filter(client=client, amount__gt=0)
          .order_by('-doc_date').values('doc_date', 'doc_type', 'amount', 'manager', 'year')[:limit])
    return list(qs)


def yoy(year, prev, **f):
    f2 = {k: v for k, v in f.items() if k not in ('date_from', 'date_to')}
    return {'now': sales_summary(year, **f2)['by_month'], 'prev': sales_summary(prev, **f2)['by_month']}


def filter_options(year):
    managers = sorted(set(SalesFact.objects.exclude(client__in=_excluded())
                          .exclude(manager='').values_list('manager', flat=True)))
    clients = sorted(set(SalesFact.objects.exclude(client__in=_excluded())
                         .values_list('client', flat=True)))
    channels = [c[0] for c in Client.CHANNELS]
    return {'managers': managers, 'clients': clients, 'channels': channels}


def _last3_sku_qty():
    """Продажи по SKU в штуках за последние 3 месяца (по SkuFact)."""
    from django.db.models import Max
    last = SkuFact.objects.aggregate(y=Max('year'))['y']
    if not last:
        return {}, None
    months = sorted(set(SkuFact.objects.filter(year=last).values_list('month', flat=True)))
    m3 = months[-3:] if len(months) >= 3 else months
    qty = {}
    for r in (SkuFact.objects.filter(year=last, month__in=m3)
              .values('sku_raw').annotate(q=Sum('qty'))):
        qty[r['sku_raw']] = r['q'] or 0
    return qty, len(m3)


def packaging_status(series=None, used=None):
    """Статус упаковки: остаток, расход/мес по продажам, на сколько хватит."""
    from .models import PackagingItem
    sku_qty, nmon = _last3_sku_qty()
    nmon = nmon or 3
    rows = []
    for it in PackagingItem.objects.all():
        q3 = sku_qty.get(it.sku, 0)
        rate = q3 / nmon if q3 else 0
        months = (it.stock / rate) if rate > 0 else None
        is_used = it.is_active_manual if it.is_active_manual is not None else (rate > 0)
        if series and it.series != series:
            continue
        if used == 'yes' and not is_used:
            continue
        if used == 'no' and is_used:
            continue
        status = ('crit' if months is not None and months < 1
                  else 'warn' if months is not None and months < 3
                  else 'ok' if months is not None else 'idle')
        rows.append({'upak': it.upak, 'series': it.series, 'stock': it.stock,
                     'rate': round(rate), 'months': months, 'status': status, 'used': is_used})
    rows.sort(key=lambda r: (r['months'] if r['months'] is not None else 9e9))
    return rows


def packaging_series_list():
    from .models import PackagingItem
    return sorted(set(PackagingItem.objects.exclude(series='').values_list('series', flat=True)))
