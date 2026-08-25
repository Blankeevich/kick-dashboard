"""
Read-only JSON API для интеграции с внешними ИИ (ChatGPT Custom GPT «Actions», Claude и др.).
Аутентификация: заголовок  X-API-Key: <ключ>  (или Authorization: Bearer <ключ>).
Ключ берётся из окружения API_KEY. Если API_KEY не задан — API отдаёт 503 (выключен).
Все эндпоинты только читают данные. Схема для подключения: /api/v1/openapi.json
"""
import os
from datetime import date
from functools import wraps
from django.http import JsonResponse
from django.core.serializers.json import DjangoJSONEncoder
from . import metrics

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


class SafeEncoder(DjangoJSONEncoder):
    def default(self, o):
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def _json(data, status=200):
    return JsonResponse(data, status=status, encoder=SafeEncoder,
                        json_dumps_params={'ensure_ascii': False})


def _g(o, k, d=None):
    if isinstance(o, dict):
        return o.get(k, d)
    return getattr(o, k, d)


def _cur():
    ys = metrics.sales_years()
    return ys[0] if ys else date.today().year


def _year(request):
    try:
        return int(request.GET.get('year'))
    except (TypeError, ValueError):
        return _cur()


def _filters(request):
    g = request.GET
    return {k: (g.get(k) or None) for k in ('manager', 'channel', 'client')}


def _limit(request, default=10):
    try:
        return max(1, min(200, int(request.GET.get('limit', default))))
    except (TypeError, ValueError):
        return default


def api_key_required(view):
    @wraps(view)
    def wrapper(request, *a, **k):
        key = os.environ.get('API_KEY')
        if not key:
            return _json({'error': 'api_disabled',
                          'detail': 'API_KEY не задан на сервере — интеграция выключена.'}, 503)
        got = request.headers.get('X-API-Key') or ''
        auth = request.headers.get('Authorization') or ''
        if auth.lower().startswith('bearer '):
            got = auth[7:].strip()
        if not got or got != key:
            return _json({'error': 'unauthorized',
                          'detail': 'Передайте валидный ключ в заголовке X-API-Key.'}, 401)
        return view(request, *a, **k)
    return wrapper


# ---------- эндпоинты ----------
def health(request):
    return _json({'status': 'ok', 'service': 'KICK BI API', 'version': 'v1',
                  'configured': bool(os.environ.get('API_KEY'))})


@api_key_required
def overview(request):
    cur = _cur(); prev = cur - 1
    s = metrics.sales_summary(cur)
    y = metrics.yoy(cur, prev)
    m = date.today().month if cur == date.today().year else 12
    now_ytd = sum(y['now'][:m]); prev_ytd = sum(y['prev'][:m]) or 1
    d = metrics.debt_summary()
    top = [{'client': _g(x, 'client'), 'debt': _g(x, 'debt_total'),
            'overdue': _g(x, 'debt_overdue'), 'overdue_days': _g(x, 'overdue_days')}
           for x in (d.get('debtors') or [])[:5]]
    return _json({
        'year': cur,
        'sales_total_vat': s['total'],
        'returns_vat': abs(s['returns']),
        'yoy_pct': round((now_ytd - prev_ytd) / prev_ytd * 100, 1),
        'debt_total': d.get('total'), 'debt_overdue': d.get('overdue'),
        'debtors_count': d.get('count'),
        'top_debtors': top,
        'currency': 'RUB', 'note': 'Суммы с НДС.',
    })


@api_key_required
def sales(request):
    yr = _year(request); prev = yr - 1; f = _filters(request)
    s = metrics.sales_summary(yr, **f)
    y = metrics.yoy(yr, prev, **f)
    return _json({'year': yr, 'filters': f, 'total_vat': s['total'],
                  'returns_vat': abs(s['returns']),
                  'by_month': [{'month': MONTHS[i], 'amount': s['by_month'][i]} for i in range(12)],
                  'yoy': {'cur': y['now'], 'prev': y['prev'], 'prev_year': prev},
                  'currency': 'RUB'})


@api_key_required
def top_clients(request):
    yr = _year(request); f = _filters(request)
    return _json({'year': yr, 'clients': metrics.top_clients(yr, _limit(request), **f)})


@api_key_required
def managers(request):
    yr = _year(request); f = _filters(request)
    return _json({'year': yr, 'managers': metrics.by_manager(yr, **f)})


@api_key_required
def top_sku(request):
    yr = _year(request)
    return _json({'year': yr, 'sku': metrics.top_sku(yr, _limit(request))})


@api_key_required
def debtors(request):
    f = _filters(request)
    only = request.GET.get('overdue') == '1'
    d = metrics.debt_summary(manager=f['manager'], client=f['client'], only_overdue=only)
    rows = [{'client': _g(x, 'client'), 'manager': _g(x, 'manager'),
             'debt_total': _g(x, 'debt_total'), 'debt_overdue': _g(x, 'debt_overdue'),
             'overdue_days': _g(x, 'overdue_days'), 'due_date': _g(x, 'due_date')}
            for x in (d.get('debtors') or [])]
    return _json({'total': d.get('total'), 'overdue': d.get('overdue'),
                  'count': d.get('count'), 'debtors': rows[:_limit(request, 20)]})


@api_key_required
def margin(request):
    out = {'note': 'Маржинальность, средневзвешенная. Себестоимость ×1.22 (НДС).'}
    try:
        out['by_channel'] = metrics.channel_margin()
    except Exception as e:
        out['by_channel_error'] = str(e)
    try:
        cm = metrics.cost_margin()
        if isinstance(cm, dict):
            out['avg_margin_pct'] = cm.get('avg_margin')
            rows = cm.get('rows') or []
        else:
            rows = cm or []
        out['positions'] = rows[:_limit(request, 30)]
    except Exception as e:
        out['positions_error'] = str(e)
    return _json(out)


@api_key_required
def client(request):
    name = request.GET.get('name')
    if not name:
        return _json({'error': 'name_required', 'detail': 'Укажите ?name=<контрагент>'}, 400)
    cur = _cur()
    try:
        prof = metrics.client_profile(name, cur, cur - 1)
    except Exception as e:
        return _json({'error': 'not_found_or_failed', 'detail': str(e)}, 404)
    return _json(prof)


@api_key_required
def signals(request):
    return _json({'signals': metrics.signals()})


# ---------- OpenAPI-схема для ChatGPT «Actions» ----------
def openapi(request):
    base = (os.environ.get('SITE_URL') or ('%s://%s' % (
        'https' if request.is_secure() else 'http', request.get_host()))).rstrip('/')

    def op(opid, summary, params=None):
        p = [{'name': n, 'in': 'query', 'required': False,
              'schema': {'type': t}, 'description': desc} for (n, t, desc) in (params or [])]
        return {'get': {'operationId': opid, 'summary': summary, 'parameters': p,
                        'responses': {'200': {'description': 'OK'}}}}

    yrp = ('year', 'integer', 'Год (по умолчанию текущий)')
    fm = ('manager', 'string', 'Фильтр по менеджеру')
    fc = ('channel', 'string', 'Фильтр по каналу (сети/опт/e-com/horeca/экспорт/стм)')
    fk = ('client', 'string', 'Фильтр по контрагенту')
    lim = ('limit', 'integer', 'Сколько записей вернуть')

    spec = {
        'openapi': '3.1.0',
        'info': {'title': 'KICK BI API', 'version': 'v1',
                 'description': 'Read-only доступ к аналитике: продажи, дебиторка, маржа, лиды, карточка клиента.'},
        'servers': [{'url': base}],
        'security': [{'ApiKeyAuth': []}],
        'components': {'securitySchemes': {
            'ApiKeyAuth': {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'}}},
        'paths': {
            '/api/v1/overview': op('getOverview', 'Ключевые показатели: продажи YTD, YoY, дебиторка, топ-должники'),
            '/api/v1/sales': op('getSales', 'Продажи за год: итог, возвраты, помесячно, год-к-году', [yrp, fm, fc, fk]),
            '/api/v1/top-clients': op('getTopClients', 'Топ контрагентов по выручке', [yrp, lim, fm, fc]),
            '/api/v1/managers': op('getManagers', 'Продажи по менеджерам', [yrp, fc]),
            '/api/v1/top-sku': op('getTopSku', 'Топ позиций (SKU) по выручке', [yrp, lim]),
            '/api/v1/debtors': op('getDebtors', 'Дебиторка: список должников, долг и просрочка',
                                  [lim, fm, fk, ('overdue', 'string', 'overdue=1 — только просроченные')]),
            '/api/v1/margin': op('getMargin', 'Маржинальность по каналам и позициям', [lim]),
            '/api/v1/client': op('getClient', 'Карточка клиента: продажи по годам и долг',
                                 [('name', 'string', 'Название контрагента (обязательно)')]),
            '/api/v1/signals': op('getSignals', 'Сигналы «что требует внимания»'),
        },
    }
    return JsonResponse(spec, json_dumps_params={'ensure_ascii': False})
