from django import forms
from django.contrib import admin
from .models import (Upload, Client, SkuMap, SalesPlan, PackagingItem, DebtLine,
                     SalesFact, DebtSnapshot, ManagerProfile, CostItem, CostSku, SkuFact, CostGroup, Lead)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('company', 'channel', 'city', 'status', 'owner', 'updated_at')
    list_filter = ('status', 'channel', 'owner')
    search_fields = ('company', 'inn', 'city', 'contact', 'phone', 'email')
    list_editable = ('status',)


@admin.register(CostGroup)
class CostGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    list_editable = ('order',)
    filter_horizontal = ('items', 'clients')


def _sku_choices(current=''):
    from django.db.models import Max
    ly = SkuFact.objects.aggregate(y=Max('year'))['y']
    skus = sorted(set(SkuFact.objects.filter(year=ly).values_list('sku_raw', flat=True))) if ly else []
    ch = [('', '— выбрать SKU —')] + [(s, s) for s in skus]
    if current and current not in skus:
        ch.append((current, current + '  (текущее)'))
    return ch


class CostItemForm(forms.ModelForm):
    class Meta:
        model = CostItem
        fields = '__all__'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        cur = self.instance.sku if self.instance and self.instance.sku else ''
        self.fields['sku'] = forms.ChoiceField(required=False, label='Основной SKU (свой бренд)',
                                               choices=_sku_choices(cur))


class CostSkuForm(forms.ModelForm):
    class Meta:
        model = CostSku
        fields = '__all__'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        cur = self.instance.sku if self.instance and self.instance.sku else ''
        self.fields['sku'] = forms.ChoiceField(required=False, choices=_sku_choices(cur))


class CostSkuInline(admin.TabularInline):
    model = CostSku
    form = CostSkuForm
    extra = 1
    verbose_name = 'СТМ / доп. SKU'
    verbose_name_plural = 'Ещё SKU этого рецепта (СТМ, другие бренды)'


@admin.register(CostItem)
class CostItemAdmin(admin.ModelAdmin):
    form = CostItemForm
    inlines = [CostSkuInline]
    list_display = ('name', 'line', 'cost', 'sku', 'updated_at')
    list_filter = ('line',)
    search_fields = ('name', 'sku')
    list_editable = ('cost',)


@admin.register(ManagerProfile)
class ManagerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'manager')
    search_fields = ('user__username', 'manager')

MONTHS_RU = [(i, n) for i, n in enumerate(
    ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
     'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'], start=1)]


@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    list_display = ('kind', 'filename', 'period_year', 'rows_loaded', 'control_sum', 'status', 'uploaded_at')
    list_filter = ('kind', 'status')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'inn', 'channel', 'credit_limit', 'excluded', 'synced_at')
    list_filter = ('channel', 'excluded')
    search_fields = ('name', 'inn', 'full_name')
    list_editable = ('channel', 'excluded')


@admin.register(SkuMap)
class SkuMapAdmin(admin.ModelAdmin):
    list_display = ('raw_name', 'real_sku', 'line', 'brand_type')
    list_filter = ('brand_type', 'line')
    search_fields = ('raw_name', 'real_sku')
    list_editable = ('real_sku', 'line', 'brand_type')


class SalesPlanForm(forms.ModelForm):
    class Meta:
        model = SalesPlan
        fields = '__all__'

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        mgrs = sorted(set(SalesFact.objects.exclude(manager='').values_list('manager', flat=True)))
        self.fields['manager'] = forms.ChoiceField(
            required=False, label='Менеджер',
            choices=[('', '— все менеджеры (общий план) —')] + [(m, m) for m in mgrs])
        self.fields['month'] = forms.TypedChoiceField(choices=MONTHS_RU, coerce=int, label='Месяц')
        self.fields['year'] = forms.TypedChoiceField(
            choices=[(y, y) for y in (2025, 2026, 2027)], coerce=int, label='Год')


@admin.register(SalesPlan)
class SalesPlanAdmin(admin.ModelAdmin):
    form = SalesPlanForm
    list_display = ('year', 'month', 'manager', 'amount', 'updated_at')
    list_filter = ('year',)


admin.site.site_header = 'KICK — админ-панель'
admin.site.site_title = 'KICK'
admin.site.index_title = 'Управление данными'


@admin.register(PackagingItem)
class PackagingItemAdmin(admin.ModelAdmin):
    list_display = ('upak', 'series', 'sku', 'stock', 'is_active_manual')
    list_filter = ('series',)
    search_fields = ('upak', 'sku')
    list_editable = ('stock', 'is_active_manual')


@admin.register(DebtLine)
class DebtLineAdmin(admin.ModelAdmin):
    list_display = ('client', 'ship_date', 'due_date', 'debt_total', 'debt_overdue', 'overdue_days', 'bucket')
    list_filter = ('bucket',)
    search_fields = ('client',)


@admin.register(DebtSnapshot)
class DebtSnapshotAdmin(admin.ModelAdmin):
    list_display = ('date', 'total', 'overdue', 'count')
