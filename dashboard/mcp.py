"""
MCP-сервер (Streamable HTTP, JSON-RPC 2.0) для интеграции сайта с Claude.
Эндпоинт: POST /mcp   ·   аутентификация: заголовок X-API-Key (тот же API_KEY, что и REST API).
Методы: initialize, notifications/initialized, tools/list, tools/call, ping.
Инструменты — те же метрики, что и REST API (только чтение).

Подключение в Claude Code:
  claude mcp add --transport http kick-bi https://erp.pkfoodrev.ru/mcp --header "X-API-Key: <ключ>"
"""
import os
import json
import uuid
from datetime import date
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from . import metrics

MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
SERVER_INFO = {'name': 'KICK BI', 'version': '1.0.0'}
DEFAULT_PROTO = '2025-06-18'


def _cur():
    ys = metrics.sales_years()
    return ys[0] if ys else date.today().year


def _g(o, k, d=None):
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


def _n(v, default=None):
    return v if v not in (None, '') else default


# ---------- данные (те же, что REST) ----------
def t_overview(**a):
    cur = _cur(); prev = cur - 1
    s = metrics.sales_summary(cur); y = metrics.yoy(cur, prev)
    m = date.today().month if cur == date.today().year else 12
    now = sum(y['now'][:m]); pr = sum(y['prev'][:m]) or 1
    d = metrics.debt_summary()
    return {'year': cur, 'sales_total_vat': s['total'], 'returns_vat': abs(s['returns']),
            'yoy_pct': round((now - pr) / pr * 100, 1), 'debt_total': d.get('total'),
            'debt_overdue': d.get('overdue'), 'debtors_count': d.get('count'),
            'top_debtors': [{'client': _g(x, 'client'), 'debt': _g(x, 'debt_total'),
                             'overdue': _g(x, 'debt_overdue'), 'overdue_days': _g(x, 'overdue_days')}
                            for x in (d.get('debtors') or [])[:5]], 'currency': 'RUB'}


def t_sales(year=None, manager=None, channel=None, client=None, **a):
    yr = int(year) if year else _cur()
    f = {'manager': _n(manager), 'channel': _n(channel), 'client': _n(client)}
    s = metrics.sales_summary(yr, **f); y = metrics.yoy(yr, yr - 1, **f)
    return {'year': yr, 'total_vat': s['total'], 'returns_vat': abs(s['returns']),
            'by_month': [{'month': MONTHS[i], 'amount': s['by_month'][i]} for i in range(12)],
            'yoy': {'cur': y['now'], 'prev': y['prev'], 'prev_year': yr - 1}}


def t_top_clients(year=None, limit=10, manager=None, channel=None, **a):
    yr = int(year) if year else _cur()
    return {'year': yr, 'clients': metrics.top_clients(yr, int(limit or 10),
            manager=_n(manager), channel=_n(channel), client=None)}


def t_managers(year=None, channel=None, **a):
    yr = int(year) if year else _cur()
    return {'year': yr, 'managers': metrics.by_manager(yr, manager=None, channel=_n(channel), client=None)}


def t_top_sku(year=None, limit=10, **a):
    yr = int(year) if year else _cur()
    return {'year': yr, 'sku': metrics.top_sku(yr, int(limit or 10))}


def t_debtors(limit=20, manager=None, client=None, overdue=None, **a):
    d = metrics.debt_summary(manager=_n(manager), client=_n(client), only_overdue=(str(overdue) == '1'))
    rows = [{'client': _g(x, 'client'), 'manager': _g(x, 'manager'),
             'debt_total': _g(x, 'debt_total'), 'debt_overdue': _g(x, 'debt_overdue'),
             'overdue_days': _g(x, 'overdue_days'), 'due_date': str(_g(x, 'due_date') or '')}
            for x in (d.get('debtors') or [])]
    return {'total': d.get('total'), 'overdue': d.get('overdue'), 'count': d.get('count'),
            'debtors': rows[:int(limit or 20)]}


def t_margin(limit=30, **a):
    out = {}
    try:
        out['by_channel'] = metrics.channel_margin()
    except Exception as e:
        out['by_channel_error'] = str(e)
    try:
        cm = metrics.cost_margin()
        rows = cm.get('rows') if isinstance(cm, dict) else (cm or [])
        out['avg_margin_pct'] = cm.get('avg_margin') if isinstance(cm, dict) else None
        out['positions'] = (rows or [])[:int(limit or 30)]
    except Exception as e:
        out['positions_error'] = str(e)
    return out


def t_client(name=None, **a):
    if not _n(name):
        return {'error': 'Укажите name (контрагент)'}
    cur = _cur()
    try:
        return metrics.client_profile(name, cur, cur - 1)
    except Exception as e:
        return {'error': 'не найдено или ошибка: %s' % e}


def t_signals(**a):
    return {'signals': metrics.signals()}


_S = lambda **p: {'type': 'object', 'properties': p}
_str = {'type': 'string'}
_int = {'type': 'integer'}

TOOLS = [
    {'name': 'get_overview', 'description': 'Ключевые показатели: продажи YTD, YoY %, дебиторка, топ-должники.',
     'inputSchema': _S(), 'fn': t_overview},
    {'name': 'get_sales', 'description': 'Продажи за год: итог с НДС, возвраты, помесячно, год-к-году. Фильтры year/manager/channel/client.',
     'inputSchema': _S(year=_int, manager=_str, channel=_str, client=_str), 'fn': t_sales},
    {'name': 'get_top_clients', 'description': 'Топ контрагентов по выручке. Параметры year, limit, manager, channel.',
     'inputSchema': _S(year=_int, limit=_int, manager=_str, channel=_str), 'fn': t_top_clients},
    {'name': 'get_managers', 'description': 'Продажи по менеджерам. Параметры year, channel.',
     'inputSchema': _S(year=_int, channel=_str), 'fn': t_managers},
    {'name': 'get_top_sku', 'description': 'Топ позиций (SKU) по выручке. Параметры year, limit.',
     'inputSchema': _S(year=_int, limit=_int), 'fn': t_top_sku},
    {'name': 'get_debtors', 'description': 'Дебиторка: должники, долг и просрочка. overdue="1" — только просроченные.',
     'inputSchema': _S(limit=_int, manager=_str, client=_str, overdue=_str), 'fn': t_debtors},
    {'name': 'get_margin', 'description': 'Маржинальность по каналам и позициям (средневзвешенная).',
     'inputSchema': _S(limit=_int), 'fn': t_margin},
    {'name': 'get_client', 'description': 'Карточка клиента: продажи по годам и долг. Параметр name (обязательно).',
     'inputSchema': {'type': 'object', 'properties': {'name': _str}, 'required': ['name']}, 'fn': t_client},
    {'name': 'get_signals', 'description': 'Сигналы «что требует внимания»: замолчавшие клиенты, рост долга, лимиты.',
     'inputSchema': _S(), 'fn': t_signals},
]
_BY_NAME = {t['name']: t for t in TOOLS}


def _rpc_result(mid, result):
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def _rpc_error(mid, code, message):
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}


def _handle(msg):
    """Обрабатывает один JSON-RPC объект. Возвращает dict-ответ или None (для нотификаций)."""
    mid = msg.get('id')
    method = msg.get('method')
    params = msg.get('params') or {}
    if method == 'initialize':
        proto = params.get('protocolVersion') or DEFAULT_PROTO
        return _rpc_result(mid, {'protocolVersion': proto,
                                 'capabilities': {'tools': {'listChanged': False}},
                                 'serverInfo': SERVER_INFO})
    if method in ('notifications/initialized', 'initialized', 'notifications/cancelled'):
        return None  # нотификация — без ответа
    if method == 'ping':
        return _rpc_result(mid, {})
    if method == 'tools/list':
        return _rpc_result(mid, {'tools': [{'name': t['name'], 'description': t['description'],
                                            'inputSchema': t['inputSchema']} for t in TOOLS]})
    if method == 'tools/call':
        name = params.get('name'); args = params.get('arguments') or {}
        tool = _BY_NAME.get(name)
        if not tool:
            return _rpc_error(mid, -32602, 'Неизвестный инструмент: %s' % name)
        try:
            data = tool['fn'](**args)
            text = json.dumps(data, ensure_ascii=False, default=str)
            return _rpc_result(mid, {'content': [{'type': 'text', 'text': text}], 'isError': False})
        except Exception as e:
            return _rpc_result(mid, {'content': [{'type': 'text', 'text': 'Ошибка: %s' % e}], 'isError': True})
    if mid is None:
        return None  # прочая нотификация
    return _rpc_error(mid, -32601, 'Метод не поддерживается: %s' % method)


@csrf_exempt
def endpoint(request, key=None):
    real = os.environ.get('API_KEY')
    if not real:
        return JsonResponse({'error': 'api_disabled'}, status=503)
    got = key or request.headers.get('X-API-Key') or ''   # ключ из URL или из заголовка
    auth = request.headers.get('Authorization') or ''
    if not got and auth.lower().startswith('bearer '):
        got = auth[7:].strip()
    if got != real:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    if request.method == 'GET':
        # опциональный SSE-стрим сервер→клиент не поддерживаем
        return HttpResponse(status=405)
    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse(_rpc_error(None, -32700, 'Parse error'), status=400)

    if isinstance(body, list):                      # батч
        out = [r for r in (_handle(m) for m in body) if r is not None]
        if not out:
            return HttpResponse(status=202)
        resp = JsonResponse(out, safe=False)
    else:
        r = _handle(body)
        if r is None:
            return HttpResponse(status=202)         # нотификация — 202 без тела
        resp = JsonResponse(r)

    resp['Mcp-Session-Id'] = request.headers.get('Mcp-Session-Id') or uuid.uuid4().hex
    return resp
