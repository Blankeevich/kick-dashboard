from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from . import metrics, loader

MONTHS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек']
CUR_YEAR, PREV_YEAR = 2026, 2025


def _filters(request):
    """Читаем селекторы из GET."""
    manager = request.GET.get('manager') or None
    channel = request.GET.get('channel') or None
    client = request.GET.get('client') or None
    return {'manager': manager, 'channel': channel, 'client': client}


def _base_ctx(request, page):
    f = _filters(request)
    opts = metrics.filter_options(CUR_YEAR)
    return {'page': page, 'cur_year': CUR_YEAR, 'prev_year': PREV_YEAR,
            'f': f, 'opts': opts, 'months': MONTHS,
            'sel_manager': f['manager'] or '', 'sel_channel': f['channel'] or '',
            'sel_client': f['client'] or ''}


@login_required
def svodka(request):
    c = _base_ctx(request, 'svodka')
    f = c['f']
    s = metrics.sales_summary(CUR_YEAR, **f)
    y = metrics.yoy(CUR_YEAR, PREV_YEAR, **f)
    ymax = max(max(y['now']), max(y['prev'])) or 1
    now7, prev7 = sum(y['now'][:7]), sum(y['prev'][:7]) or 1
    day = metrics.sales_by_day(CUR_YEAR, **f)
    dmax = max([d['amount'] for d in day['days']], default=1) or 1
    d = metrics.debt_summary(manager=f['manager'], client=f['client'])
    c.update({
        'sales_total': s['total'], 'returns': abs(s['returns']),
        'yoy_bars': [{'m': MONTHS[i], 'now_h': round(y['now'][i]/ymax*100),
                      'prev_h': round(y['prev'][i]/ymax*100)} for i in range(12)],
        'yoy_delta': round((now7-prev7)/prev7*100),
        'day': day, 'day_bars': [{'d': x['day'], 'h': round(x['amount']/dmax*100),
                                  'amount': x['amount']} for x in day['days']],
        'top_clients': metrics.top_clients(CUR_YEAR, 5, **f),
        'managers': metrics.by_manager(CUR_YEAR, **f),
        'debt': d, 'debtors': d['debtors'][:4],
    })
    return render(request, 'dashboard/svodka.html', c)


@login_required
def prodazhi(request):
    c = _base_ctx(request, 'prodazhi')
    f = c['f']
    s = metrics.sales_summary(CUR_YEAR, **f)
    y = metrics.yoy(CUR_YEAR, PREV_YEAR, **f)
    now7, prev7 = sum(y['now'][:7]), sum(y['prev'][:7]) or 1
    c.update({
        'sales_total': s['total'], 'returns': abs(s['returns']),
        'yoy_delta': round((now7-prev7)/prev7*100),
        'all_clients': metrics.all_clients(CUR_YEAR, **f),
        'managers': metrics.by_manager(CUR_YEAR, **f),
        'top_sku': metrics.top_sku(CUR_YEAR, 8),
    })
    return render(request, 'dashboard/prodazhi.html', c)


@login_required
def debitorka(request):
    c = _base_ctx(request, 'debitorka')
    f = c['f']
    d = metrics.debt_summary(manager=f['manager'], client=f['client'])
    c.update({'debt': d, 'debtors': d['debtors']})
    return render(request, 'dashboard/debitorka.html', c)


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


class Login(LoginView):
    template_name = 'dashboard/login.html'
