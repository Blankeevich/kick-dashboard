"""Бэкап базы: pg_dump → gzip → локальная папка (ротация) + письмо с дампом на офсайт-адрес.
Почему офсайт критично: лиды/CRM, история, справочник себестоимости есть ТОЛЬКО в этой БД,
в 1С их нет — при потере VPS восстановить неоткуда.

Запуск:   manage.py backup_db                 # дамп + письмо, если задан BACKUP_EMAIL/ALERT_EMAIL
          manage.py backup_db --no-email
          manage.py backup_db --keep 30
По расписанию: systemd timer раз в день.
"""
import os
import gzip
import shutil
import subprocess
from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand
from dashboard.notify import send_email


class Command(BaseCommand):
    help = 'pg_dump в файл + офсайт по почте'

    def add_arguments(self, parser):
        parser.add_argument('--dir', default=None, help='папка бэкапов (по умолч. BASE_DIR/backups)')
        parser.add_argument('--keep', type=int, default=14, help='сколько последних дампов хранить')
        parser.add_argument('--no-email', action='store_true')

    def handle(self, *a, **o):
        db = settings.DATABASES['default']
        engine = db.get('ENGINE', '')
        if 'postgres' not in engine:
            self.stdout.write(self.style.WARNING('БД не PostgreSQL (%s) — бэкап pg_dump пропущен' % engine))
            return
        bdir = o['dir'] or os.path.join(str(settings.BASE_DIR), 'backups')
        os.makedirs(bdir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M')
        raw = os.path.join(bdir, 'kick_%s.sql' % ts)
        gz = raw + '.gz'
        env = dict(os.environ)
        if db.get('PASSWORD'):
            env['PGPASSWORD'] = db['PASSWORD']
        cmd = ['pg_dump', '-h', db.get('HOST') or 'localhost', '-p', str(db.get('PORT') or 5432),
               '-U', db.get('USER') or 'postgres', '-d', db.get('NAME'), '-f', raw, '--no-owner']
        try:
            subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR('pg_dump не найден в PATH')); return
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR('pg_dump ошибка: %s' % (e.stderr or e))); return
        with open(raw, 'rb') as f_in, gzip.open(gz, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(raw)
        size = os.path.getsize(gz)
        # ротация
        dumps = sorted(f for f in os.listdir(bdir) if f.startswith('kick_') and f.endswith('.sql.gz'))
        for old in dumps[:-o['keep']]:
            os.remove(os.path.join(bdir, old))
        msg = 'Бэкап создан: %s (%.1f МБ), хранится последних %d' % (gz, size / 1e6, o['keep'])
        self.stdout.write(self.style.SUCCESS(msg))
        # офсайт по почте
        if not o['no_email']:
            to = os.environ.get('BACKUP_EMAIL') or os.environ.get('ALERT_EMAIL')
            if size > 24 * 1024 * 1024:
                send_email('KICK бэкап: дамп слишком большой для письма',
                           'Дамп %s = %.1f МБ, не влезает в письмо. Настрой выгрузку в облако.' % (gz, size / 1e6), to=to)
                self.stdout.write(self.style.WARNING('Дамп >24МБ — письмом не отправлен, только локально'))
            else:
                with open(gz, 'rb') as f:
                    data = f.read()
                ok, detail = send_email('KICK бэкап БД %s' % ts,
                                        'Ежедневный дамп базы KICK во вложении.', to=to,
                                        attachments=[(os.path.basename(gz), data)])
                self.stdout.write(('офсайт: ' + detail) if ok else self.style.ERROR('офсайт не ушёл: ' + detail))
