"""
Режим «только просмотр» для директора и учредителя.

Аккаунты в группе `readonly` видят весь сайт, но не могут ничего менять:
любой небезопасный HTTP-метод (POST/PUT/PATCH/DELETE) возвращает 403.
Это серверная гарантия — даже если в вёрстке останется кнопка, изменение
не пройдёт. Скрытие кнопок в шаблонах — только для удобства.

API (/api/) и MCP (/mcp) не трогаем: у них своя авторизация по ключу,
браузерный readonly-пользователь туда не ходит.
"""
from django.http import HttpResponseForbidden

READONLY_GROUP = 'readonly'
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS', 'TRACE')
EXEMPT_PREFIXES = ('/api/', '/mcp')


def is_viewer(user):
    """True, если пользователь состоит в группе readonly. Результат кэшируется на объекте user."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    cached = getattr(user, '_is_viewer', None)
    if cached is None:
        cached = user.groups.filter(name=READONLY_GROUP).exists()
        user._is_viewer = cached
    return cached


class ReadOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method not in SAFE_METHODS
                and not request.path.startswith(EXEMPT_PREFIXES)
                and is_viewer(request.user)):
            return HttpResponseForbidden(
                'Режим просмотра: этот аккаунт может только смотреть данные, без изменений.'
            )
        return self.get_response(request)
