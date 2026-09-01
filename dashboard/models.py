"""
Модели данных дашборда KICK.
Три слоя (по инженерным требованиям):
  - raw:   загруженные файлы (сырьё, хранится навсегда)
  - core:  нормализованные факты из 1С (продажи, дебиторка) — только запись загрузчиком
  - справочники/планы: редактируемый слой (у нас источник правды)
"""
from django.db import models
from django.contrib.auth.models import User


# ---------- RAW: журнал загрузок ----------
class Upload(models.Model):
    """Каждая загрузка файла 1С — с хешем для идемпотентности."""
    KIND = [('sales_client', 'Продажи по контрагентам'),
            ('sales_sku', 'Продажи по номенклатуре'),
            ('debt', 'Дебиторка'),
            ('packaging', 'Остатки упаковки'),
            ('contractors', 'Справочник контрагентов')]
    kind = models.CharField('Тип отчёта', max_length=20, choices=KIND)
    filename = models.CharField('Имя файла', max_length=255)
    file_hash = models.CharField('Хеш файла', max_length=64, db_index=True)
    period_year = models.IntegerField('Год данных', null=True, blank=True)
    uploaded_at = models.DateTimeField('Загружено', auto_now_add=True)
    uploaded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    rows_loaded = models.IntegerField('Строк загружено', default=0)
    control_sum = models.BigIntegerField('Контрольная сумма', default=0)
    status = models.CharField('Статус', max_length=20, default='ok')
    note = models.TextField('Примечание', blank=True)

    class Meta:
        verbose_name = 'Загрузка'
        verbose_name_plural = 'Загрузки данных'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.get_kind_display()} · {self.filename} · {self.uploaded_at:%d.%m.%Y %H:%M}'


# ---------- CORE: факты продаж ----------
class SalesFact(models.Model):
    """Строка продаж: контрагент × месяц. Только с НДС (осн. показатель)."""
    DOC_TYPES = [('Реализация', 'Реализация'), ('Корректировка', 'Корректировка'),
                 ('Комиссионер', 'Отчёт комиссионера'), ('Прочее', 'Прочее')]
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE)
    doc_type = models.CharField(max_length=20, choices=DOC_TYPES, default='Реализация')
    doc_date = models.DateField(null=True, blank=True)
    client = models.CharField('Контрагент', max_length=255, db_index=True)
    manager = models.CharField('Менеджер', max_length=255, blank=True)
    year = models.IntegerField(db_index=True)
    month = models.IntegerField()
    qty = models.FloatField('Количество', default=0)
    amount = models.BigIntegerField('Сумма с НДС', default=0)
    doc_no = models.CharField('Номер документа', max_length=60, blank=True, db_index=True)
    schet_no = models.CharField('Номер счёта на оплату', max_length=60, blank=True, db_index=True)
    base_no = models.CharField('Основание (реализация) для корректировки', max_length=60, blank=True, default='', db_index=True)

    class Meta:
        verbose_name = 'Продажа'
        verbose_name_plural = 'Продажи (факт из 1С)'
        indexes = [models.Index(fields=['year', 'month']), models.Index(fields=['client'])]


class SkuDoc(models.Model):
    """Строка реализации по номенклатуре с номером документа — для сшивки SKU × контрагент."""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE)
    doc_no = models.CharField('Номер документа', max_length=60, db_index=True)
    sku_raw = models.CharField('Карточка 1С', max_length=255, db_index=True)
    year = models.IntegerField(db_index=True)
    qty = models.FloatField(default=0)
    amount = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = 'Реализация SKU'
        verbose_name_plural = 'Реализации по SKU (для сшивки с клиентом)'


class SkuFact(models.Model):
    """Строка продаж по номенклатуре: карточка × месяц."""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE)
    sku_raw = models.CharField('Карточка 1С', max_length=255, db_index=True)
    brand_type = models.CharField('Тип', max_length=15, default='own')  # own/private_label/non_product
    year = models.IntegerField(db_index=True)
    month = models.IntegerField()
    qty = models.FloatField(default=0)
    amount = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = 'Продажа SKU'
        verbose_name_plural = 'Продажи по SKU (факт)'


class DebtFact(models.Model):
    """Снимок дебиторки на дату выгрузки."""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE)
    snapshot_date = models.DateField('Дата снимка', null=True, db_index=True)
    client = models.CharField('Контрагент', max_length=255, db_index=True)
    manager = models.CharField('Менеджер', max_length=255, blank=True)
    ship_date = models.DateField('Дата отгрузки', null=True, blank=True)
    due_date = models.DateField('Срок оплаты', null=True, blank=True)
    debt_total = models.BigIntegerField('Долг всего', default=0)
    debt_overdue = models.BigIntegerField('Просрочено', default=0)
    overdue_days = models.IntegerField('Дней просрочки', default=0)

    class Meta:
        verbose_name = 'Дебиторка'
        verbose_name_plural = 'Дебиторка (факт)'


class DebtSnapshot(models.Model):
    """Снимок дебиторки на дату загрузки — для истории/динамики долга."""
    date = models.DateField('Дата снимка', unique=True)
    total = models.BigIntegerField('Долг всего', default=0)
    overdue = models.BigIntegerField('Просрочено', default=0)
    count = models.IntegerField('Должников', default=0)

    class Meta:
        verbose_name = 'Снимок дебиторки'
        verbose_name_plural = 'История дебиторки (снимки)'
        ordering = ['-date']


class DebtClientSnapshot(models.Model):
    """Долг клиента на дату снимка — для динамики «кто растёт / кто гасит»."""
    date = models.DateField('Дата снимка', db_index=True)
    client = models.CharField('Контрагент', max_length=255, db_index=True)
    debt_total = models.BigIntegerField('Долг', default=0)
    debt_overdue = models.BigIntegerField('Просрочено', default=0)

    class Meta:
        verbose_name = 'Долг клиента (снимок)'
        verbose_name_plural = 'История долга по клиентам'
        unique_together = [('date', 'client')]


class DebtLine(models.Model):
    """Отдельная реализация в составе долга клиента (расшифровка по срокам из 1С)."""
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE)
    snapshot_date = models.DateField('Дата снимка', null=True, db_index=True)
    client = models.CharField('Контрагент', max_length=255, db_index=True)
    doc_no = models.CharField('Номер документа', max_length=60, blank=True)
    ship_date = models.DateField('Дата отгрузки', null=True, blank=True)
    due_date = models.DateField('Срок оплаты', null=True, blank=True)
    debt_total = models.BigIntegerField('Долг по документу', default=0)
    debt_overdue = models.BigIntegerField('Просрочено', default=0)
    overdue_days = models.IntegerField('Дней просрочки', default=0)
    bucket = models.CharField('Корзина срока', max_length=20, blank=True)

    class Meta:
        verbose_name = 'Реализация в долге'
        verbose_name_plural = 'Дебиторка по реализациям'
        indexes = [models.Index(fields=['client'])]


# ---------- Справочники (редактируемый слой) ----------
class Client(models.Model):
    """Справочник клиентов: канал, лимит. Связь с фактом по имени контрагента."""
    CHANNELS = [('сети', 'Сети'), ('e-com', 'E-com'), ('опт', 'Опт'),
                ('экспорт', 'Экспорт'), ('horeca', 'HoReCa'), ('стм', 'СТМ'), ('прочее', 'Прочее')]
    name = models.CharField('Контрагент (как в 1С)', max_length=255, unique=True)
    channel = models.CharField('Канал', max_length=10, choices=CHANNELS, default='прочее')
    credit_limit = models.BigIntegerField('Кредитный лимит', null=True, blank=True)
    excluded = models.BooleanField('Исключить из аналитики', default=False)
    note = models.TextField('Комментарий', blank=True)
    # реквизиты из справочника 1С (обновляются загрузкой)
    inn = models.CharField('ИНН', max_length=15, blank=True, db_index=True)
    kpp = models.CharField('КПП', max_length=15, blank=True)
    ogrn = models.CharField('ОГРН', max_length=20, blank=True)
    full_name = models.CharField('Полное наименование', max_length=400, blank=True)
    manager = models.CharField('Менеджер', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=120, blank=True)
    contact = models.CharField('Контактное лицо', max_length=255, blank=True)
    email = models.CharField('Email', max_length=180, blank=True)
    city = models.CharField('Город / регион', max_length=180, blank=True)
    address = models.CharField('Адрес', max_length=400, blank=True)
    bank = models.CharField('Банк', max_length=255, blank=True)
    account = models.CharField('Расчётный счёт', max_length=40, blank=True)
    bik = models.CharField('БИК', max_length=15, blank=True)
    STATUS = [('потенциальный', 'Потенциальный'), ('активный', 'Активный'),
              ('приостановлен', 'Приостановлен'), ('бывший', 'Бывший')]
    status = models.CharField('Статус', max_length=15, choices=STATUS, blank=True)
    payment_terms = models.CharField('Оплата (предоплата / отсрочка N дней)', max_length=120, blank=True)
    retro_bonus = models.CharField('Ретро-бонус / особые условия', max_length=120, blank=True)
    contract = models.CharField('Договор (№, дата, срок)', max_length=200, blank=True)
    delivery = models.CharField('Доставка', max_length=200, blank=True)
    min_order = models.IntegerField('Мин. заказ, ₽', null=True, blank=True)
    synced_at = models.DateField('Актуализировано из 1С', null=True, blank=True)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Справочник клиентов'
        ordering = ['name']

    def __str__(self):
        return self.name


class ManagerProfile(models.Model):
    """Связь аккаунта с менеджером (как он зовётся в продажах) — для прав на редактирование своих клиентов."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name='Аккаунт')
    manager = models.CharField('Менеджер (как в продажах)', max_length=255, blank=True)
    can_edit_all = models.BooleanField('Может редактировать всех клиентов', default=False)

    class Meta:
        verbose_name = 'Профиль менеджера'
        verbose_name_plural = 'Профили менеджеров (права)'

    def __str__(self):
        return f'{self.user.username} → {self.manager or "—"}'


class SkuMap(models.Model):
    """Справочник номенклатуры: карточка 1С → реальный SKU, линейка, тип."""
    TYPES = [('own', 'Свой бренд'), ('private_label', 'СТМ'), ('non_product', 'Непродуктовое')]
    raw_name = models.CharField('Карточка 1С', max_length=255, unique=True)
    real_sku = models.CharField('Реальный SKU', max_length=255, blank=True)
    line = models.CharField('Линейка', max_length=100, blank=True)
    brand_type = models.CharField('Тип', max_length=15, choices=TYPES, default='own')

    class Meta:
        verbose_name = 'SKU'
        verbose_name_plural = 'Справочник номенклатуры'
        ordering = ['raw_name']

    def __str__(self):
        return self.real_sku or self.raw_name


class SalesPlan(models.Model):
    """План продаж — ручной ввод. Статус: введён вручную."""
    year = models.IntegerField('Год')
    month = models.IntegerField('Месяц')
    manager = models.CharField('Менеджер', max_length=255, blank=True)
    amount = models.BigIntegerField('План, ₽ с НДС')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = 'План продаж'
        verbose_name_plural = 'Планы продаж'
        unique_together = [('year', 'month', 'manager')]

    def __str__(self):
        return f'{self.month:02d}.{self.year} {self.manager or "все"} — {self.amount:,} ₽'


class CostItem(models.Model):
    """Себестоимость позиции (без НДС) из файла + привязка к SKU для цены продажи."""
    line = models.CharField('Линейка', max_length=100, blank=True)
    name = models.CharField('Позиция (из файла себестоимости)', max_length=255, unique=True)
    cost = models.FloatField('Себестоимость без НДС, ₽')
    sku = models.CharField('SKU для цены продажи (карточка 1С)', max_length=255, blank=True, db_index=True)
    updated_at = models.DateField('Обновлено', null=True, blank=True)

    class Meta:
        verbose_name = 'Себестоимость'
        verbose_name_plural = 'Себестоимость (справочник)'
        ordering = ['line', 'name']

    def save(self, *args, **kwargs):
        # SCD-lite: при изменении себестоимости фиксируем запись в истории (с датой),
        # чтобы маржа прошлых периодов не переписывалась текущей ценой.
        super().save(*args, **kwargs)
        last = self.history.first()
        if last is None or round(last.cost, 2) != round(self.cost or 0, 2):
            CostHistory.objects.create(cost_item=self, cost=self.cost or 0)

    def __str__(self):
        return self.name


class CostHistory(models.Model):
    """История себестоимости позиции (SCD-lite): цена + дата вступления в силу."""
    cost_item = models.ForeignKey(CostItem, on_delete=models.CASCADE, related_name='history')
    cost = models.FloatField('Себестоимость без НДС, ₽')
    effective_from = models.DateField('Действует с', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'История себестоимости'
        verbose_name_plural = 'История себестоимости'
        ordering = ['-effective_from', '-id']

    def __str__(self):
        return '%s: %s c %s' % (self.cost_item_id, self.cost, self.effective_from)


class CostGroup(models.Model):
    """Своя группа позиций себестоимости (например «Перекрёсток», «Сети») — ведётся вручную."""
    name = models.CharField('Название группы', max_length=120, unique=True)
    items = models.ManyToManyField('CostItem', blank=True, related_name='groups',
                                   verbose_name='Позиции себестоимости (ручной список)')
    clients = models.ManyToManyField('Client', blank=True, related_name='cost_groups',
                                     verbose_name='Контрагенты (считать по их реальным покупкам)')
    order = models.IntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Группа себестоимости'
        verbose_name_plural = 'Группы себестоимости (свои)'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class CostSku(models.Model):
    """Доп. SKU для позиции себестоимости: один рецепт — несколько брендов (свой + СТМ)."""
    cost = models.ForeignKey(CostItem, on_delete=models.CASCADE, related_name='skus',
                             verbose_name='Позиция себестоимости')
    sku = models.CharField('SKU (карточка 1С)', max_length=255, db_index=True)

    class Meta:
        verbose_name = 'SKU позиции'
        verbose_name_plural = 'SKU позиций себестоимости'
        unique_together = [('cost', 'sku')]

    def __str__(self):
        return self.sku


class SalesManager(models.Model):
    """Справочник менеджеров (для выбора в лидах и т.п.). Заводится вручную + из продаж."""
    name = models.CharField('Менеджер', max_length=160, unique=True)
    active = models.BooleanField('Активен', default=True)

    class Meta:
        verbose_name = 'Менеджер'
        verbose_name_plural = 'Менеджеры (справочник)'
        ordering = ['name']

    def __str__(self):
        return self.name


class LeadStage(models.Model):
    """Настраиваемый этап воронки (колонка на канбан-доске). Пользователь заводит сам."""
    name = models.CharField('Название этапа', max_length=80)
    order = models.IntegerField('Порядок', default=0)
    color = models.CharField('Цвет', max_length=9, default='#6d5bd0')
    is_won = models.BooleanField('Успех (стал клиентом)', default=False)
    is_lost = models.BooleanField('Отказ', default=False)

    class Meta:
        verbose_name = 'Этап воронки'
        verbose_name_plural = 'Этапы воронки (лиды)'
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class Lead(models.Model):
    """Потенциальный клиент (лид). Этап воронки — ссылка на настраиваемый LeadStage."""
    CHANNELS = [
        ('сети', 'Сетевой ритейл'),
        ('зож', 'ЗОЖ-розница'),
        ('e-com', 'E-com / маркетплейс'),
        ('horeca', 'HoReCa'),
        ('опт', 'Опт / дистрибуция'),
        ('стм', 'СТМ / контракт'),
        ('прочее', 'Прочее'),
    ]
    company = models.CharField('Компания', max_length=255, db_index=True)
    inn = models.CharField('ИНН', max_length=15, blank=True, db_index=True)
    channel = models.CharField('Канал', max_length=20, choices=CHANNELS, blank=True)
    city = models.CharField('Город', max_length=120, blank=True)
    contact = models.CharField('Контактное лицо', max_length=160, blank=True)
    phone = models.CharField('Телефон', max_length=80, blank=True)
    email = models.CharField('Email', max_length=160, blank=True)
    website = models.CharField('Сайт', max_length=200, blank=True)
    socials = models.TextField('Соцсети (ссылки)', blank=True,
                               help_text='Ссылки на соцсети, по одной в строке или через запятую')
    source = models.CharField('Источник', max_length=160, blank=True,
                              help_text='Где нашли: веб-поиск, выставка, рекомендация…')
    stage = models.ForeignKey(LeadStage, verbose_name='Этап', null=True, blank=True,
                              on_delete=models.SET_NULL, related_name='leads')
    potential = models.BigIntegerField('Потенциал сделки, ₽', null=True, blank=True)
    owner = models.CharField('Ответственный', max_length=160, blank=True)
    note = models.TextField('Заметки', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)
    last_touch = models.DateField('Последний контакт', null=True, blank=True)
    next_action = models.DateField('Следующий шаг (дата)', null=True, blank=True)
    converted = models.BooleanField('Заведён клиентом', default=False)

    class Meta:
        verbose_name = 'Лид'
        verbose_name_plural = 'Лиды (потенциальные клиенты)'
        ordering = ['-updated_at']

    def __str__(self):
        return self.company


class LeadNote(models.Model):
    """Запись в истории лида (активность/заметка/событие)."""
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='notes')
    text = models.TextField('Текст')
    author = models.CharField('Автор', max_length=120, blank=True)
    created_at = models.DateTimeField('Когда', auto_now_add=True)

    class Meta:
        verbose_name = 'История лида'
        verbose_name_plural = 'История лидов'
        ordering = ['-created_at']

    def __str__(self):
        return '%s: %s' % (self.lead_id, self.text[:40])


class LeadLog(models.Model):
    """Журнал действий по лидам (аудит). Виден только админам."""
    created_at = models.DateTimeField('Когда', auto_now_add=True, db_index=True)
    user = models.CharField('Кто', max_length=120, blank=True)
    action = models.CharField('Действие', max_length=40)
    lead_id = models.IntegerField('ID лида', null=True, blank=True)
    company = models.CharField('Компания', max_length=255, blank=True)
    detail = models.TextField('Детали', blank=True)

    class Meta:
        verbose_name = 'Лог лида'
        verbose_name_plural = 'Логи лидов (аудит)'
        ordering = ['-created_at']

    def __str__(self):
        return '%s %s %s' % (self.created_at, self.user, self.action)


class Project(models.Model):
    """Проект в трекере задач."""
    STATUS = [('active', 'Активен'), ('archived', 'В архиве')]
    name = models.CharField('Название', max_length=160, unique=True)
    description = models.TextField('Описание', blank=True)
    color = models.CharField('Цвет', max_length=9, default='#6d5bd0')
    status = models.CharField('Статус', max_length=10, choices=STATUS, default='active')
    order = models.IntegerField('Порядок', default=0)
    created_at = models.DateTimeField('Создан', auto_now_add=True)

    class Meta:
        verbose_name = 'Проект'
        verbose_name_plural = 'Проекты'
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.name


class TaskStage(models.Model):
    """Настраиваемый этап — колонка канбана трекера (общий для всех проектов)."""
    name = models.CharField('Название этапа', max_length=80)
    order = models.IntegerField('Порядок', default=0)
    color = models.CharField('Цвет', max_length=9, default='#6d5bd0')
    is_done = models.BooleanField('Выполнено (для прогресса)', default=False)

    class Meta:
        verbose_name = 'Этап задач'
        verbose_name_plural = 'Этапы задач'
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class Task(models.Model):
    """Задача в проекте. Колонки канбана — настраиваемые этапы (TaskStage)."""
    PRIORITY = [('low', 'Низкий'), ('med', 'Средний'), ('high', 'Высокий')]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks', verbose_name='Проект')
    title = models.CharField('Задача', max_length=255)
    description = models.TextField('Описание', blank=True)
    stage = models.ForeignKey(TaskStage, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='tasks', verbose_name='Этап')
    priority = models.CharField('Приоритет', max_length=6, choices=PRIORITY, default='med')
    assignees = models.ManyToManyField('SalesManager', blank=True, related_name='tasks', verbose_name='Исполнители')
    due_date = models.DateField('Срок', null=True, blank=True)
    client = models.CharField('Клиент (привязка)', max_length=255, blank=True)
    lead = models.ForeignKey('Lead', null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='tasks', verbose_name='Лид (привязка)')
    order = models.IntegerField('Порядок', default=0)
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлена', auto_now=True)
    done_at = models.DateField('Выполнена', null=True, blank=True)

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи (трекер)'
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title


class PackagingItem(models.Model):
    """Справочник упаковки: связь с батончиком (для расхода по продажам) + остаток."""
    upak = models.CharField('Упаковка', max_length=255, unique=True)
    sku = models.CharField('Батончик (SKU для расхода)', max_length=255, db_index=True)
    series = models.CharField('Серия', max_length=40, blank=True)
    stock = models.BigIntegerField('Остаток', default=0)
    snap_key = models.CharField('Ключ снимка', max_length=255, blank=True, db_index=True,
                                help_text='Нормализованное имя из файла-снимка для авто-обновления остатка')
    is_active_manual = models.BooleanField('Используется (ручной флаг)', null=True, blank=True,
                                           help_text='Пусто = определяется автоматически по продажам')

    class Meta:
        verbose_name = 'Упаковка'
        verbose_name_plural = 'Справочник упаковки'
        ordering = ['series', 'upak']

    def __str__(self):
        return self.upak
