# KICK — BI-дашборд

Django-приложение: продажи, дебиторка, сводка на данных из 1С.

## Запуск на сервере (кратко)
1. `pip install -r requirements.txt`
2. настроить PostgreSQL в kick/settings.py
3. `python manage.py migrate`
4. `python manage.py createsuperuser`
5. `gunicorn kick.wsgi`

Полная инструкция — при развёртывании.
