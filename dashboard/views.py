from datetime import datetime
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from . import metrics, loader
from .models import Upload

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
CUR_YEAR, PREV_YEAR = 2026, 2025


def _pdate(s):
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _filters(request):
    return {'manager': request.GET.get('manager') or None,
            'channel': request.GET.get('channel') or None,
            'client': request.GET.get('client') or None,
            'date_from': _pdate(request.GET.get('date_from')),
            'date_to': _pdate(request.GET.get('date_to'))}


def _base_ctx(request, page):
    f = _filters(request)
    opts = metrics.filter_options(CUR_YEAR)
    last_sales = Upload.objects.filter(kind='sales_client').order_by('-uploaded_at').first()
    last_debt = Upload.objects.filter(kind='debt').order_by('-uploaded_at').first()
    return {'page': page, 'cur_year': CUR_YEAR, 'prev_year': PREV_YEAR, 'f': f, 'opts': opts,
            'last_sales': last_sales, 'last_debt': last_debt,
            'months': MONTHS,
            'sel_manager': f['manager'] or '', 'sel_channel': f['channel'] or '',
            'sel_client': f['client'] or '',
            'sel_from': request.GET.get('date_from', ''), 'sel_to': request.GET.get('date_to', ''),
            'has_period': bool(f['date_from'] and f['date_to'])}


@login_required
def svodka(request):
    c = _base_ctx(request, 'svodka')
    f = c['f']
    year = None if c['has_period'] else CUR_YEAR
    s = metrics.sales_summary(year, **f)
    y = metrics.yoy(CUR_YEAR, PREV_YEAR, **{k: f[k] for k in ('manager', 'channel', 'client')})
    ymax = max(max(y['now']), max(y['prev'])) or 1
    now7, prev7 = sum(y['now'][:7]), sum(y['prev'][:7]) or 1
    day = metrics.sales_by_day(year, **f)
    dmax = max([d['amount'] for d in day['days']], default=1) or 1
    d = metrics.debt_summary(manager=f['manager'], client=f['client'])
    c.update({
        'sales_total': s['total'], 'returns': abs(s['returns']),
        'yoy_bars': [{'m': MONTHS[i], 'now_h': round(y['now'][i] / ymax * 100),
                      'prev_h': round(y['prev'][i] / ymax * 100),
                      'now_v': y['now'][i], 'prev_v': y['prev'][i]} for i in range(12)],
        'yoy_delta': round((now7 - prev7) / prev7 * 100),
        'day': day, 'day_bars': [{'d': x['day'], 'h': round(x['amount'] / dmax * 100),
                                  'amount': x['amount']} for x in day['days']],
        'top_clients': metrics.top_clients(year, 5, **f),
        'managers': metrics.by_manager(year, **f),
        'debt': d, 'debtors': d['debtors'][:4],
    })
    return render(request, 'dashboard/svodka.html', c)


@login_required
def prodazhi(request):
    c = _base_ctx(request, 'prodazhi')
    f = c['f']
    year = None if c['has_period'] else CUR_YEAR
    s = metrics.sales_summary(year, **f)
    y = metrics.yoy(CUR_YEAR, PREV_YEAR, **{k: f[k] for k in ('manager', 'channel', 'client')})
    now7, prev7 = sum(y['now'][:7]), sum(y['prev'][:7]) or 1
    c.update({
        'sales_total': s['total'], 'returns': abs(s['returns']),
        'yoy_delta': round((now7 - prev7) / prev7 * 100),
        'all_clients': metrics.all_clients(year, **f),
        'managers': metrics.by_manager(year, **f),
        'top_sku': metrics.top_sku(CUR_YEAR, 8),
        'plans': metrics.plan_status(CUR_YEAR),
    })
    return render(request, 'dashboard/prodazhi.html', c)


@login_required
def debitorka(request):
    c = _base_ctx(request, 'debitorka')
    f = c['f']
    only_overdue = request.GET.get('overdue') == '1'
    order = request.GET.get('order', '-debt_total')
    d = metrics.debt_summary(manager=f['manager'], client=f['client'],
                             only_overdue=only_overdue, order=order)
    aging = metrics.debt_aging(manager=f['manager'], client=f['client'])
    bmax = max([b['amount'] for b in aging['buckets']], default=1) or 1
    for b in aging['buckets']:
        b['h'] = round(b['amount'] / bmax * 100)
    c.update({'debt': d, 'debtors': d['debtors'], 'aging': aging,
              'only_overdue': only_overdue, 'order': order})
    return render(request, 'dashboard/debitorka.html', c)


@login_required
def debtor(request, client):
    c = _base_ctx(request, 'debitorka')
    d = metrics.debt_summary(client=client)
    lines = metrics.debt_lines(client)          # реальная расшифровка по реализациям из 1С
    fallback = []
    if not lines:                                # расшифровки нет — старый приблизительный список
        fallback = metrics.client_sales(client)
        for x in fallback:
            x['date_str'] = x['doc_date'].strftime('%d.%m.%Y') if x['doc_date'] else '—'
    c.update({'client_name': client, 'debt': d,
              'debtor_row': d['debtors'][0] if d['debtors'] else None,
              'lines': lines, 'sales': fallback})
    return render(request, 'dashboard/debtor.html', c)


@login_required
def upload(request):
    msg = []
    if request.method == 'POST':
        fn_map = {'sales_client': loader.load_sales_client,
                  'sales_sku': loader.load_sales_sku, 'debt': loader.load_debt}
        for key, fn in fn_map.items():
            f = request.FILES.get(key)
            if f:
                r = fn(f, f.name, request.user)
                msg.append(f'{key}: пропущено — {r["reason"]}' if r.get('skipped')
                           else f'{key}: загружено {r["rows"]} строк, сумма {r["total"]:,} ₽')
    return render(request, 'dashboard/upload.html', {'msg': msg, 'page': 'upload'})


@login_required
def upakovka(request):
    series = request.GET.get('series') or None
    used = request.GET.get('used') or None
    rows = metrics.packaging_status(series=series, used=used)
    crit = [r for r in rows if r['status'] == 'crit']
    warn = [r for r in rows if r['status'] == 'warn']
    return render(request, 'dashboard/upakovka.html', {
        'page': 'upakovka', 'rows': rows, 'crit': crit, 'warn': warn,
        'series_list': metrics.packaging_series_list(),
        'sel_series': series or '', 'sel_used': used or '',
        'cur_year': CUR_YEAR, 'prev_year': PREV_YEAR,
    })


class Login(LoginView):
    template_name = 'dashboard/login.html'
