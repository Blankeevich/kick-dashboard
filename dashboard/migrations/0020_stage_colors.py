from django.db import migrations


COLORS = {
    'Новый': '#6d5bd0',
    'Написали': '#3b82f6',
    'Ответил': '#0ea5e9',
    'Переговоры': '#f59e0b',
    'Стал клиентом': '#2fa84f',
    'Отказ': '#b42318',
}


def paint(apps, schema_editor):
    LeadStage = apps.get_model('dashboard', 'LeadStage')
    palette = ['#6d5bd0', '#3b82f6', '#0ea5e9', '#14b8a6', '#f59e0b', '#ef7a3d', '#2fa84f', '#b42318']
    for i, st in enumerate(LeadStage.objects.all().order_by('order', 'id')):
        st.color = COLORS.get(st.name, palette[i % len(palette)])
        st.save(update_fields=['color'])


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0019_lead_converted_lead_next_action_leadstage_color_and_more')]
    operations = [migrations.RunPython(paint, migrations.RunPython.noop)]
