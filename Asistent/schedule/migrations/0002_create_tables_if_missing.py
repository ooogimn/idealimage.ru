# Если 0001_initial был применён с --fake (из-за InconsistentMigrationHistory),
# таблицы в БД не созданы. Эта миграция создаёт их при первом применении.

from django.db import connection, migrations


def create_tables_if_missing(apps, schema_editor):
    def table_exists(name):
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
                LIMIT 1
                """,
                [name],
            )
            return bool(cur.fetchone())

    with connection.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'Asistent_aischedule'
            LIMIT 1
        """)
        if cur.fetchone():
            return
    # Если таблиц-источников ещё нет (частично восстановленная БД),
    # пропускаем создание schedule-таблиц, чтобы не ломать migrate.
    if not table_exists("Asistent_prompttemplate"):
        return
    AISchedule = apps.get_model('schedule', 'AISchedule')
    AIScheduleRun = apps.get_model('schedule', 'AIScheduleRun')
    schema_editor.create_model(AISchedule)
    schema_editor.create_model(AIScheduleRun)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('schedule', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_tables_if_missing, noop),
    ]
