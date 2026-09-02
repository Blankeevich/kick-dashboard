#!/usr/bin/env bash
# Забирает выгрузки 1С из почты и грузит в базу.
# Почтовые креды (MAIL_USER / MAIL_PASS / MAIL_HOST) берёт из двух источников:
#   1) файл /opt/kick-dashboard/.env
#   2) окружение systemd-сервиса kick (если они заданы там)
# Так работает и вручную, и из таймера — независимо от того, где лежат креды.
cd /opt/kick-dashboard || exit 1
set -a
[ -f .env ] && . ./.env
set +a
while IFS= read -r kv; do
  [ -n "$kv" ] && export "$kv"
done < <(systemctl show kick -p Environment --value 2>/dev/null | tr ' ' '\n')
exec venv/bin/python manage.py fetch_mail "$@"
