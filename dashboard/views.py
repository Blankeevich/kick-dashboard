from datetime import datetime, date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from . import metrics, loader
from .models import Upload

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
MONTHS_FULL = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
               'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
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


def _period_presets():
    """Быстрые периоды: неделя / месяц / квартал / год (относительно сегодня)."""
    t = date.today()
    q_start = date(t.year, ((t.month - 1) // 3) * 3 + 1, 1)
    iso = lambda d: d.strftime('%Y-%m-%d')
    return [
        {'label': 'Неделя', 'df': iso(t - timedelta(days=6)), 'dt': iso(t)},
        {'label': 'Месяц', 'df': iso(date(t.year, t.month, 1)), 'dt': iso(t)},
        {'label': 'Квартал', 'df': iso(q_start), 'dt': iso(t)},
        {'label': 'Год', 'df': iso(date(t.year, 1, 1)), 'dt': iso(t)},
    ]


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
            'has_period': bool(f['date_from'] and f['date_to']),
            'presets': _period_presets()}


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
        'plans': metrics.plan_status(year, manager=f['manager'],
                                     date_from=f['date_from'], date_to=f['date_to']),
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
        'plans': metrics.plan_status(year, manager=f['manager'],
                                     date_from=f['date_from'], date_to=f['date_to']),
    })
    return render(request, 'dashboard/prodazhi.html', c)


@login_required
def debitorka(request):
    c = _base_ctx(request, 'debitorka')
    f = c['f']
    only_overdue = request.GET.get('overdue') == '1'
    order = request.GET.get('order', '-debt_total')
    snap_dates = metrics.debt_dates()
    sel_snap = _pdate(request.GET.get('snap'))
    if sel_snap not in snap_dates:
        sel_snap = snap_dates[0] if snap_dates else None
    d = metrics.debt_summary(manager=f['manager'], client=f['client'],
                             only_overdue=only_overdue, order=order, snapshot=sel_snap)
    aging = metrics.debt_aging(manager=f['manager'], client=f['client'], snapshot=sel_snap)
    bmax = max([b['amount'] for b in aging['buckets']], default=1) or 1
    for b in aging['buckets']:
        b['h'] = round(b['amount'] / bmax * 100)
    hist = metrics.debt_history()
    hmax = max([h['total'] for h in hist], default=1) or 1
    hist_bars = [{'date': h['date'], 'total': h['total'], 'overdue': h['overdue'],
                  'h': round(h['total'] / hmax * 100)} for h in hist]
    c.update({'debt': d, 'debtors': d['debtors'], 'aging': aging,
              'hist_bars': hist_bars, 'only_overdue': only_overdue, 'order': order,
              'snap_dates': snap_dates, 'sel_snap': sel_snap, 'is_latest': sel_snap == (snap_dates[0] if snap_dates else None)})
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
        fp = request.FILES.get('packaging')
        if fp:
            r = loader.load_packaging_snapshot(fp, fp.name, request.user)
            if r.get('skipped'):
                msg.append(f'упаковка: пропущено — {r["reason"]}')
            else:
                m = f' · не сопоставлено: {len(r["missed"])}' if r['missed'] else ''
                msg.append(f'упаковка: обновлено остатков {r["updated"]} из {r["total"]} (лист {r["sheet"]}){m}')
        ca, cs = request.FILES.get('contractors_all'), request.FILES.get('contractors_sup')
        if ca and cs:
            r = loader.load_contractors(ca, cs, request.user)
            if r.get('skipped'):
                msg.append(f'контрагенты: пропущено — {r["reason"]}')
            else:
                msg.append(f'контрагенты: добавлено {r["created"]}, обновлено {r["updated"]}, '
                           f'отсеяно мусора {r["junk"]} (поставщиков {r["suppliers"]})')
        elif ca or cs:
            msg.append('контрагенты: нужны ОБА файла — общий и поставщики')
    return render(request, 'dashboard/upload.html', {'msg': msg, 'page': 'upload'})


@login_required
def clients(request):
    q = (request.GET.get('q') or '').strip().lower()
    years, all_rows = metrics.clients_list(CUR_YEAR)
    rows = [r for r in all_rows if q in r['name'].lower() or q in r['inn']] if q else all_rows
    last_sales = Upload.objects.filter(kind='sales_client').order_by('-uploaded_at').first()
    last_debt = Upload.objects.filter(kind='debt').order_by('-uploaded_at').first()
    return render(request, 'dashboard/clients.html', {
        'page': 'clients', 'rows': rows, 'years': years, 'q': request.GET.get('q', ''), 'found': len(rows),
        'total_clients': len(all_rows), 'cur_year': CUR_YEAR,
        'total_sales': sum(r['sales'] for r in rows), 'total_debt': sum(r['debt'] for r in rows),
        'last_sales': last_sales, 'last_debt': last_debt})


@login_required
def client_card(request, client):
    from .models import Client, ManagerProfile
    p = metrics.client_profile(client, CUR_YEAR, PREV_YEAR)
    prof = ManagerProfile.objects.filter(user=request.user).first()
    can_edit = bool(request.user.is_staff or (prof and prof.manager and prof.manager == p['owner_manager']))
    saved = False
    if request.method == 'POST' and can_edit:
        obj, _ = Client.objects.get_or_create(name=client)
        for f in ('channel', 'status', 'full_name', 'kpp', 'ogrn', 'phone', 'contact', 'email',
                  'city', 'address', 'bank', 'account', 'bik', 'payment_terms', 'retro_bonus',
                  'contract', 'delivery', 'note'):
            setattr(obj, f, request.POST.get(f, '').strip())
        lim = request.POST.get('credit_limit', '').replace(' ', '')
        obj.credit_limit = int(lim) if lim.isdigit() else None
        mo = request.POST.get('min_order', '').replace(' ', '')
        obj.min_order = int(mo) if mo.isdigit() else None
        obj.save()
        p = metrics.client_profile(client, CUR_YEAR, PREV_YEAR)
        saved = True
    last_sales = Upload.objects.filter(kind='sales_client').order_by('-uploaded_at').first()
    last_debt = Upload.objects.filter(kind='debt').order_by('-uploaded_at').first()
    ymax = max(max(p['now']), max(p['prev'])) or 1
    bars = [{'m': MONTHS[i], 'now_h': round(p['now'][i] / ymax * 100),
             'prev_h': round(p['prev'][i] / ymax * 100),
             'now_v': p['now'][i], 'prev_v': p['prev'][i]} for i in range(12)]
    hmax = max([h['debt_total'] for h in p['hist']], default=1) or 1
    hist = [{'date': h['date'], 'total': h['debt_total'], 'h': round(h['debt_total'] / hmax * 100)} for h in p['hist']]
    return render(request, 'dashboard/client_card.html', {
        'page': 'clients', 'client_name': client, 'p': p, 'bars': bars, 'hist': hist,
        'cur_year': CUR_YEAR, 'prev_year': PREV_YEAR,
        'can_edit': can_edit, 'saved': saved, 'channels': Client.CHANNELS, 'statuses': Client.STATUS,
        'last_sales': last_sales, 'last_debt': last_debt})


@login_required
def oplaty(request):
    ym = request.GET.get('ym', '')
    try:
        y, m = map(int, ym.split('-'))
        date(y, m, 1)
    except (ValueError, TypeError):
        t = date.today()
        y, m = t.year, t.month
    cal = metrics.payment_calendar(y, m)
    prev = date(y, m, 1) - timedelta(days=1)
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return render(request, 'dashboard/oplaty.html', {
        'page': 'oplaty', 'cal': cal, 'month_name': MONTHS_FULL[m - 1], 'year': y,
        'prev_ym': f'{prev.year}-{prev.month:02d}', 'next_ym': f'{nxt.year}-{nxt.month:02d}',
        'weekdays': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
        'last_debt': Upload.objects.filter(kind='debt').order_by('-uploaded_at').first(),
    })


@login_required
def oplaty_day(request, day):
    try:
        d = datetime.strptime(day, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        d = date.today()
    rows = metrics.payment_day(d)
    return render(request, 'dashboard/oplaty_day.html', {
        'page': 'oplaty', 'day': d, 'rows': rows,
        'total': sum(r['debt_total'] for r in rows),
        'overdue': sum(r['debt_overdue'] for r in rows),
        'back_ym': f'{d.year}-{d.month:02d}',
    })


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
