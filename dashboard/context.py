"""Контекст-процессор: флаг is_viewer доступен во всех шаблонах."""
from .middleware import is_viewer


def viewer_flag(request):
    return {'is_viewer': is_viewer(getattr(request, 'user', None))}
