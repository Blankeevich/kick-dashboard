# ops — авто-забор почты (выгрузки 1С)

Раз в 30 минут сервер читает почтовый ящик, находит вложения `.xlsx/.xls`,
определяет тип отчёта по имени файла и грузит в базу тем же загрузчиком, что и форма
«Загрузить данные». Маршрутизация по имени файла (см. `dashboard/management/commands/fetch_mail.py`):

| в имени файла | куда грузим        |
|---------------|--------------------|
| `задолженност`| дебиторка          |
| `номенклатур` | продажи по SKU     |
| `контрагент`  | продажи по клиентам|

Почтовые доступы (`MAIL_USER`, `MAIL_PASS`, `MAIL_HOST`) — в `/opt/kick-dashboard/.env`
или в окружении сервиса `kick`. В код/гит не коммитятся.

## Установка таймера

```bash
cd /opt/kick-dashboard
chmod +x ops/run_fetch_mail.sh
sudo cp ops/kick-fetch.service /etc/systemd/system/
sudo cp ops/kick-fetch.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kick-fetch.timer
systemctl list-timers kick-fetch.timer     # проверить расписание
```

## Забрать письма прямо сейчас (вручную)

```bash
/opt/kick-dashboard/ops/run_fetch_mail.sh
```

## Диагностика

```bash
systemctl status kick-fetch.timer          # активен ли таймер
journalctl -u kick-fetch.service -n 50     # что было в последних запусках
```

Письма помечаются прочитанными только после успешной загрузки — если забор упал,
письмо останется непрочитанным и подхватится в следующий заход.
