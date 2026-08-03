from django.db import migrations


def seed(apps, schema_editor):
    SalesManager = apps.get_model('dashboard', 'SalesManager')
    SalesFact = apps.get_model('dashboard', 'SalesFact')
    names = set(SalesFact.objects.exclude(manager='').values_list('manager', flat=True).distinct())
    names.add('Бордюгова Виктория Анатольевна')
    for n in names:
        n = (n or '').strip()
        if n:
            SalesManager.objects.get_or_create(name=n)


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0022_salesmanager')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
