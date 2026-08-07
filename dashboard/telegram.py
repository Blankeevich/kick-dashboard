"""Телеграм-логика: утренняя сводка, блоки метрик, обработчик команд бота.
Отправка — через dashboard.notify.send_telegram (прокси Cloudflare)."""
from datetime import date, timedelta
from django.db.models import Sum, Max
from django.utils import timezone
from . import metrics
from .models import SalesFact, DebtFact, DebtLine, Lead
from .notify import send_telegram

MRU = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
       'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']


def _n(x):
    return '{:,.0f}'.format(round(x or 0)).replace(',', ' ')


def _excl():
    try:
        return list(metrics._excluded())
    except Exception:
        return []


def _cur_year():
    return SalesFact.objects.aggregate(y=Max('year'))['y'] or date.today().year


def _snap():
    return DebtFact.objects.aggregate(d=Max('snapshot_date'))['d']


# ---------- блоки ----------
def sales_block():
    y = _cur_year()
    today = date.today()
    m = today.month
    q = SalesFact.objects.exclude(client__in=_excl())
    cur = q.filter(year=y, month=m).aggregate(s=Sum('amount'))['s'] or 0
    yest = today - timedelta(days=1)
    day = q.filter(doc_date=yest).aggregate(s=Sum('amount'))['s'] or 0
    return '📈 <b>Продажи</b>\nЗа %s: %s ₽\nВчера (%s): %s ₽' % (MRU[m], _n(cur), yest.strftime('%d.%m'), _n(day))


def debt_block():
    snap = _snap()
    if not snap:
        return '💰 <b>Дебиторка</b>: нет данных'
    a = (DebtFact.objects.filter(snapshot_date=snap).exclude(client__in=_excl())
         .aggregate(t=Sum('debt_total'), o=Sum('debt_overdue')))
    return '💰 <b>Дебиторка</b> (на %s)\nВсего: %s ₽\nПросрочено: %s ₽' % (
        snap.strftime('%d.%m'), _n(a['t']), _n(a['o']))


def payments_today_block():
    snap = _snap()
    today = date.today()
    if not snap:
        return ''
    rows = DebtLine.objects.filter(snapshot_date=snap, due_date=today)
    s = rows.aggregate(x=Sum('debt_total'))['x'] or 0
    n = rows.values('client').distinct().count()
    if not s:
        return '📅 <b>Оплаты сегодня</b>: нет'
    return '📅 <b>Оплаты сегодня</b>: %s ₽ от %d клиентов' % (_n(s), n)


def leads_block():
    day_ago = timezone.now() - timedelta(days=1)
    new = Lead.objects.filter(created_at__gte=day_ago).count()
    active = Lead.objects.exclude(stage__is_won=True).exclude(stage__is_lost=True).count()
    return '👥 <b>Лиды</b>\nНовых за сутки: %d\nВ работе: %d' % (new, active)


def top_debtors_text(n=5):
    snap = _snap()
    if not snap:
        return ''
    rows = (DebtFact.objects.filter(snapshot_date=snap).exclude(client__in=_excl())
            .values('client').annotate(t=Sum('debt_total'), o=Sum('debt_overdue')).order_by('-t')[:n])
    lines = ['<b>Топ должников:</b>']
    for r in rows:
        ov = (' · просрочка %s' % _n(r['o'])) if r['o'] else ''
        lines.append('• %s — %s ₽%s' % (r['client'][:34], _n(r['t']), ov))
    return '\n'.join(lines)


def top_clients_text(n=5):
    y = _cur_year()
    rows = (SalesFact.objects.exclude(client__in=_excl()).filter(year=y)
            .values('client').annotate(s=Sum('amount')).order_by('-s')[:n])
    lines = ['<b>Топ клиентов %d:</b>' % y]
    for r in rows:
        lines.append('• %s — %s ₽' % (r['client'][:34], _n(r['s'])))
    return '\n'.join(lines)


def overdue_text(n=8):
    snap = _snap()
    if not snap:
        return 'Нет данных дебиторки'
    rows = (DebtLine.objects.filter(snapshot_date=snap, debt_overdue__gt=0)
            .order_by('-debt_overdue')[:n])
    if not rows:
        return '✅ Просрочки нет'
    lines = ['🔴 <b>Просрочка</b>:']
    for l in rows:
        lines.append('• %s — %s ₽ (%s дн)' % (l.client[:30], _n(l.debt_overdue), l.overdue_days))
    return '\n'.join(lines)


def leads_funnel_text():
    from .models import LeadStage
    lines = ['👥 <b>Воронка лидов</b>:']
    for st in LeadStage.objects.all():
        lines.append('• %s — %d' % (st.name, st.leads.count()))
    return '\n'.join(lines)


def digest_text():
    parts = ['☀️ <b>KICK — сводка %s</b>' % date.today().strftime('%d.%m.%Y'), '',
             sales_block(), '', debt_block(), '', payments_today_block(), '', leads_block()]
    return '\n'.join(p for p in parts if p is not None)


# ---------- команды бота ----------
HELP = ('Команды:\n/сводка — полная сводка\n/продажи — продажи + топ клиентов\n'
        '/долги — дебиторка + топ должников\n/просрочка — что просрочено\n'
        '/оплаты — кто платит сегодня\n/лиды — воронка лидов')


def handle_update(update):
    msg = update.get('message') or update.get('channel_post') or {}
    text = (msg.get('text') or '').strip()
    chat = (msg.get('chat') or {}).get('id')
    if not chat or not text:
        return
    cmd = text.split()[0].lower().lstrip('/').split('@')[0]
    if cmd in ('start', 'help'):
        reply = 'Привет! Я бот KICK.\n\n' + HELP
    elif cmd.startswith('свод'):
        reply = digest_text()
    elif cmd.startswith('прод'):
        reply = sales_block() + '\n\n' + top_clients_text()
    elif cmd.startswith('долг'):
        reply = debt_block() + '\n\n' + top_debtors_text()
    elif cmd.startswith('просроч'):
        reply = overdue_text()
    elif cmd.startswith('оплат'):
        reply = payments_today_block()
    elif cmd.startswith('лид'):
        reply = leads_funnel_text()
    else:
        reply = 'Не понял команду.\n\n' + HELP
    send_telegram(reply, chat_id=chat)
