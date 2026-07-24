"""
Витрины: агрегация фактов из базы в цифры для дашборда.
Все функции принимают фильтры (год, менеджер, канал, контрагент) — селекторы рабочие.
"""
from django.db.models import Sum, Count
from .models import SalesFact, SkuFact, DebtFact, Client

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def _excluded():
    return set(Client.objects.filter(excluded=True).values_list('name', flat=True))


def _clients_in_channel(channel):
    return set(Client.objects.filter(channel=channel).values_list('name', flat=True))


def sales_qs(year, manager=None, channel=None, client=None):
    """Базовый queryset продаж с применёнными фильтрами."""
    qs = SalesFact.objects.filter(year=year).exclude(client__in=_excluded())
    if manager:
        qs = qs.filter(manager=manager)
    if client:
        qs = qs.filter(client=client)
    if channel:
        qs = qs.filter(client__in=_clients_in_channel(channel))
    return qs


def sales_summary(year, **f):
    qs = sales_qs(year, **f)
    total = qs.aggregate(s=Sum('amount'))['s'] or 0
    returns = qs.filter(amount__lt=0).aggregate(s=Sum('amount'))['s'] or 0
    by_month = [0] * 12
    for row in qs.values('month').annotate(s=Sum('amount')):
        by_month[row['month'] - 1] = row['s'] or 0
    return {'total': total, 'returns': returns, 'by_month': by_month}


def all_clients(year, **f):
    """Все контрагенты с суммами — для полного списка (прокрутка)."""
    qs = sales_qs(year, **f)
    total = qs.aggregate(s=Sum('amount'))['s'] or 1
    rows = qs.values('client').annotate(s=Sum('amount')).order_by('-s')
    return [{'name': r['client'], 'amount': r['s'], 'share': round(r['s'] / total * 100, 1)} for r in rows]


def top_clients(year, limit=5, **f):
    return all_clients(year, **f)[:limit]


def by_manager(year, **f):
    # менеджерский разрез игнорирует фильтр по менеджеру (показываем всех)
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


def sales_by_day(year, month=None, **f):
    """Продажи по дням (из даты документа). Если month не задан — последний месяц с данными."""
    qs = sales_qs(year, **f).filter(doc_date__isnull=False, amount__gt=0)
    if month is None:
        last = qs.order_by('-doc_date').values_list('doc_date', flat=True).first()
        if not last:
            return {'month': None, 'days': []}
        month = last.month
    rows = (qs.filter(doc_date__month=month).values('doc_date')
            .annotate(s=Sum('amount')).order_by('doc_date'))
    return {'month': month, 'month_name': MONTHS[month - 1],
            'days': [{'day': r['doc_date'].day, 'amount': r['s']} for r in rows]}


def top_sku(year, limit=8):
    qs = (SkuFact.objects.filter(year=year)
          .values('sku_raw').annotate(s=Sum('amount'), q=Sum('qty')).order_by('-s')[:limit])
    return [{'name': r['sku_raw'], 'amount': r['s'], 'qty': int(r['q'] or 0),
             'price': round(r['s'] / r['q']) if r['q'] else 0} for r in qs]


def debt_summary(manager=None, client=None):
    qs = DebtFact.objects.exclude(client__in=_excluded()).filter(debt_total__gte=1000)
    if manager:
        qs = qs.filter(manager=manager)
    if client:
        qs = qs.filter(client=client)
    total = qs.aggregate(s=Sum('debt_total'))['s'] or 0
    overdue = qs.aggregate(s=Sum('debt_overdue'))['s'] or 0
    debtors = list(qs.order_by('-debt_total').values(
        'client', 'manager', 'debt_total', 'debt_overdue', 'overdue_days', 'due_date'))
    return {'total': total, 'overdue': overdue,
            'share': round(overdue / total * 100, 1) if total else 0,
            'count': qs.count(), 'debtors': debtors}


def yoy(year, prev, **f):
    return {'now': sales_summary(year, **f)['by_month'], 'prev': sales_summary(prev, **f)['by_month']}


def filter_options(year):
    """Списки для селекторов."""
    managers = sorted(set(SalesFact.objects.exclude(client__in=_excluded())
                          .exclude(manager='').values_list('manager', flat=True)))
    clients = sorted(set(SalesFact.objects.filter(year=year).exclude(client__in=_excluded())
                         .values_list('client', flat=True)))
    channels = [c[0] for c in Client.CHANNELS]
    return {'managers': managers, 'clients': clients, 'channels': channels}
