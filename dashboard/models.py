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

    class Meta:
        verbose_name = 'Продажа'
        verbose_name_plural = 'Продажи (факт из 1С)'
        indexes = [models.Index(fields=['year', 'month']), models.Index(fields=['client'])]


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
    full_name = models.CharField('Полное наименование', max_length=400, blank=True)
    manager = models.CharField('Менеджер', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=120, blank=True)
    contact = models.CharField('Контактное лицо', max_length=255, blank=True)
    email = models.CharField('Email', max_length=180, blank=True)
    city = models.CharField('Город', max_length=180, blank=True)
    address = models.CharField('Адрес', max_length=400, blank=True)
    synced_at = models.DateField('Актуализировано из 1С', null=True, blank=True)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Справочник клиентов'
        ordering = ['name']

    def __str__(self):
        return self.name


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
