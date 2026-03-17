# Generated manually: установка задержки 300 сек для всех расписаний гороскопов

from django.db import migrations


def set_horoscope_delay_300(apps, schema_editor):
    """Выставить generation_delay=300 (5 мин) для всех расписаний с шаблоном категории horoscope."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'Asistent_prompttemplate'
            LIMIT 1
        """)
        if not cursor.fetchone():
            return  # таблица ещё не создана (например, после восстановления БД)
    AISchedule = apps.get_model('Asistent', 'AISchedule')
    PromptTemplate = apps.get_model('Asistent', 'PromptTemplate')
    horoscope_template_ids = list(
        PromptTemplate.objects.filter(category='horoscope').values_list('id', flat=True)
    )
    if not horoscope_template_ids:
        return
    schedules = AISchedule.objects.filter(prompt_template_id__in=horoscope_template_ids)
    updated = 0
    for s in schedules:
        payload = dict(s.payload_template or {})
        if payload.get('generation_delay') == 300:
            continue
        payload['generation_delay'] = 300
        s.payload_template = payload
        s.save(update_fields=['payload_template'])
        updated += 1
    if updated:
        print(f"  [0078] Обновлено расписаний гороскопов (generation_delay=300): {updated}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('Asistent', '0077_alter_systemlog_logger_name'),
    ]

    operations = [
        migrations.RunPython(set_horoscope_delay_300, noop),
    ]
