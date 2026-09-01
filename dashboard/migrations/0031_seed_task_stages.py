from django.db import migrations


def seed(apps, schema_editor):
    TaskStage = apps.get_model('dashboard', 'TaskStage')
    Task = apps.get_model('dashboard', 'Task')
    if TaskStage.objects.count() == 0:
        defs = [('Надо сделать', '#94a3b8', False),
                ('В работе', '#6d5bd0', False),
                ('На проверке', '#f59e0b', False),
                ('Готово', '#10b981', True)]
        for i, (n, c, d) in enumerate(defs):
            TaskStage.objects.create(name=n, order=i, color=c, is_done=d)
    first = TaskStage.objects.order_by('order', 'id').first()
    if first:
        Task.objects.filter(stage__isnull=True).update(stage=first)


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0030_taskstage_remove_task_assignee_remove_task_status_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
