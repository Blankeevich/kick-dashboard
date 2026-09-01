"""
Создаёт (или обновляет) read-only аккаунты для директора и учредителя.

Запуск:
    ./venv/bin/python manage.py make_viewers --password 'Foodrev2026'

Аккаунты попадают в группу `readonly` (см. ReadOnlyMiddleware): видят весь сайт,
но не могут ничего менять. is_staff=False — значит нет доступа в админку и в раздел
«Загрузить данные». Команда идемпотентна — можно запускать повторно, чтобы сбросить пароль.
"""
from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand

# логин → отображаемое имя
VIEWERS = [
    ('ceo', 'Директор'),
    ('ceo1', 'Учредитель'),
]


class Command(BaseCommand):
    help = 'Создаёт read-only аккаунты (директор, учредитель) в группе readonly'

    def add_arguments(self, parser):
        parser.add_argument('--password', required=True, help='Пароль для обоих аккаунтов')

    def handle(self, *args, **opts):
        pw = opts['password']
        grp, _ = Group.objects.get_or_create(name='readonly')
        for username, label in VIEWERS:
            u, created = User.objects.get_or_create(username=username)
            u.is_staff = False
            u.is_superuser = False
            u.is_active = True
            u.first_name = label
            u.set_password(pw)
            u.save()
            u.groups.add(grp)
            state = 'создан' if created else 'обновлён'
            self.stdout.write(self.style.SUCCESS(f'  {state}: {username} ({label})'))
        self.stdout.write(self.style.SUCCESS('Готово. Оба аккаунта — только просмотр, без прав на изменение.'))
