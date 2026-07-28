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
    years = metrics.sales_years()
    try:
        chart_y = int(request.GET.get('y'))
    except (TypeError, ValueError):
        chart_y = None
    if chart_y not in years:
        chart_y = CUR_YEAR if CUR_YEAR in years or not years else years[0]
    y = metrics.yoy(chart_y, chart_y - 1, **{k: f[k] for k in ('manager', 'channel', 'client')})
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
        'chart_y': chart_y, 'chart_prev': chart_y - 1, 'sales_years': years,
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
    if not request.user.is_staff:                 # загрузка данных — только для админов
        return render(request, 'dashboard/upload.html',
                      {'page': 'upload', 'msg': [], 'no_access': True})
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
def export_xlsx(request):
    import io
    import openpyxl
    from django.http import HttpResponse
    kind = request.GET.get('kind', 'clients')
    wb = openpyxl.Workbook()
    ws = wb.active
    if kind == 'debt':
        ws.title = 'Дебиторка'
        d = metrics.debt_summary()
        ws.append(['Клиент', 'Долг', 'Просрочено', 'Дней просрочки', 'Срок оплаты', 'Менеджер'])
        for x in d['debtors']:
            ws.append([x['client'], x['debt_total'], x['debt_overdue'], x['overdue_days'],
                       x['due_date'].strftime('%d.%m.%Y') if x['due_date'] else '', x['manager']])
    elif kind == 'rfm':
        ws.title = 'Сегменты'
        data = metrics.rfm()
        ws.append(['Клиент', 'Сегмент', 'ABC', 'Последний заказ', 'Дней', 'Заказов', 'Выручка'])
        for r in data['rows']:
            ws.append([r['client'], r['seg'], r['abc'], r['last'].strftime('%d.%m.%Y'),
                       r['r_days'], r['f'], r['m']])
    else:
        kind = 'clients'
        ws.title = 'Клиенты'
        years, rows = metrics.clients_list(CUR_YEAR)
        ws.append(['Клиент', 'ИНН', 'Канал'] + [f'Продажи {y}' for y in years] + ['Долг', 'Просрочено'])
        for r in rows:
            ws.append([r['name'], r['inn'], r['channel']] + r['by_year'] + [r['debt'], r['overdue']])
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    resp = HttpResponse(bio.read(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{kind}.xlsx"'
    return resp


@login_required
def managers(request):
    return render(request, 'dashboard/managers.html',
                  {'page': 'managers', 'rows': metrics.managers_list(CUR_YEAR), 'cur_year': CUR_YEAR})


@login_required
def manager_card(request, manager):
    p = metrics.manager_profile(manager)
    ymax = max([b['total'] for b in p['by_year']], default=1) or 1
    for b in p['by_year']:
        b['h'] = round(b['total'] / ymax * 100)
    return render(request, 'dashboard/manager_card.html', {'page': 'managers', 'p': p})


@login_required
def rfm(request):
    data = metrics.rfm()
    seg = request.GET.get('seg') or ''
    abc = request.GET.get('abc') or ''
    rows = data['rows']
    if seg:
        rows = [r for r in rows if r['seg'] == seg]
    if abc:
        rows = [r for r in rows if r['abc'] == abc]
    rows = sorted(rows, key=lambda r: -r['m'])[:400]
    return render(request, 'dashboard/rfm.html', {
        'page': 'rfm', 'segments': data['segments'], 'rows': rows,
        'total_clients': data['total_clients'], 'sel_seg': seg, 'sel_abc': abc,
        'shown': len(rows)})


@login_required
def signals(request):
    return render(request, 'dashboard/signals.html',
                  {'page': 'signals', 's': metrics.signals(), 'cur_year': CUR_YEAR})


@login_required
def sravnenie(request):
    ov = metrics.year_overview()
    if ov.get('years'):
        gmax = max((max(v) for v in ov['monthly'].values()), default=1) or 1
        palette = ['#d7cdec', '#b7a2e0', '#9670d0', '#783CBD', '#5a2c90']
        W, H = 720, 200
        lines = []
        for idx, y in enumerate(ov['years']):
            pts = []
            for mi in range(12):
                x = round(mi / 11 * (W - 20) + 10)
                yy = round(H - (ov['monthly'][y][mi] / gmax) * (H - 24) - 10)
                pts.append(f'{x},{yy}')
            lines.append({'year': y, 'points': ' '.join(pts),
                          'color': palette[idx % len(palette)]})
        ov['lines'] = lines
        ov['svg_w'], ov['svg_h'] = W, H
        rmax = max((r['total'] for r in ov['revenue']), default=1) or 1
        for r in ov['revenue']:
            r['h'] = round(r['total'] / rmax * 100)
    forgotten_n = len(metrics.forgotten_clients(CUR_YEAR)) if ov.get('years') else 0
    return render(request, 'dashboard/sravnenie.html', {'page': 'sravnenie', 'ov': ov,
                  'months': MONTHS, 'forgotten_n': forgotten_n, 'cur_year': CUR_YEAR})


@login_required
def sravnenie_drill(request):
    kind = request.GET.get('kind')
    try:
        year = int(request.GET.get('year'))
    except (TypeError, ValueError):
        year = CUR_YEAR
    if kind == 'forgotten':
        rows = metrics.forgotten_clients(year)
        title = f'Забытые клиенты'
        sub = f'покупали раньше, но в {year} — ни разу'
    elif kind == 'lost':
        rows = metrics.lost_clients(year)
        title = f'Клиенты, ушедшие в {year}'
        sub = f'покупали в {year - 1}, но не в {year}'
    else:
        lo = int(request.GET.get('lo') or 0)
        hi = request.GET.get('hi')
        hi = int(hi) if hi else None
        rows = metrics.bucket_clients(year, lo, hi)
        rng = f'{lo // 1000}к–{hi // 1000}к' if hi else f'{lo // 1000}к+'
        absent = request.GET.get('absent') == '1'
        if absent:                       # только те, кто в текущем году не заказывал
            cur_set = set(metrics._year_client_sales(CUR_YEAR))
            rows = [r for r in rows if r['name'] not in cur_set]
        title = f'Клиенты {rng} ₽ · {year}' + (f' · не заказывали в {CUR_YEAR}' if absent else '')
        sub = (f'из корзины {rng} за {year}, кто в {CUR_YEAR} не сделал ни заказа'
               if absent else f'выручка за {year} в диапазоне {rng} ₽')
        return render(request, 'dashboard/sravnenie_drill.html', {
            'page': 'sravnenie', 'rows': rows, 'title': title, 'sub': sub,
            'total': sum(r['sales'] for r in rows), 'year': year, 'bucket': True,
            'lo': lo, 'hi': hi or '', 'absent': absent, 'cur_year': CUR_YEAR,
            'show_absent': year != CUR_YEAR})
    return render(request, 'dashboard/sravnenie_drill.html', {
        'page': 'sravnenie', 'rows': rows, 'title': title, 'sub': sub,
        'total': sum(r['sales'] for r in rows), 'year': year})


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
    years = metrics.sales_years()
    try:
        sel_y = int(request.GET.get('y'))
    except (TypeError, ValueError):
        sel_y = None
    if sel_y not in years:
        sel_y = years[0] if years else CUR_YEAR
    p = metrics.client_profile(client, sel_y, sel_y - 1)
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
        'cur_year': sel_y, 'prev_year': sel_y - 1, 'sales_years': years, 'sel_y': sel_y,
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
        'forecast': metrics.payment_forecast(8),
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
