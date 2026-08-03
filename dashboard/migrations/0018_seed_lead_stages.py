from django.db import migrations


DEFAULTS = [
    ('Новый', 0, False, False),
    ('Написали', 1, False, False),
    ('Ответил', 2, False, False),
    ('Переговоры', 3, False, False),
    ('Стал клиентом', 4, True, False),
    ('Отказ', 5, False, True),
]


def seed(apps, schema_editor):
    LeadStage = apps.get_model('dashboard', 'LeadStage')
    Lead = apps.get_model('dashboard', 'Lead')
    if LeadStage.objects.exists():
        return
    stages = {}
    for name, order, won, lost in DEFAULTS:
        stages[name] = LeadStage.objects.create(name=name, order=order, is_won=won, is_lost=lost)
    # если вдруг были лиды без этапа — кладём в первый
    first = stages['Новый']
    Lead.objects.filter(stage__isnull=True).update(stage=first)


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0017_leadstage_remove_lead_status_lead_stage')]
    operations = [migrations.RunPython(seed, unseed)]
