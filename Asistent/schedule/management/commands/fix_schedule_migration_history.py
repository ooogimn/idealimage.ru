# -*- coding: utf-8 -*-
"""
Исправление истории миграций: 0074 применена до появления schedule.0001_initial.
1) Помечает schedule.0001_initial как применённую (--fake).
2) Создаёт таблицы Asistent_aischedule и Asistent_aischedulerun, если их ещё нет.
Запуск: python manage.py fix_schedule_migration_history
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Исправляет историю миграций (fake schedule.0001) и создаёт таблицы расписаний при необходимости"

    def handle(self, *args, **options):
        recorder = MigrationRecorder(connection)
        applied = set(recorder.applied_migrations())

        # 1) Пометить schedule.0001_initial как применённую, если ещё не помечена
        schedule_0001 = ("schedule", "0001_initial")
        if schedule_0001 not in applied:
            self.stdout.write("Помечаем schedule.0001_initial как применённую (fake)...")
            recorder.record_applied("schedule", "0001_initial")
            self.stdout.write(self.style.SUCCESS("  schedule.0001_initial записана в django_migrations."))
        else:
            self.stdout.write("schedule.0001_initial уже в истории.")

        # 2) Проверить, есть ли таблицы
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'Asistent_aischedule'
                LIMIT 1
            """)
            table_exists = cursor.fetchone() is not None

        if table_exists:
            self.stdout.write(self.style.SUCCESS("Таблицы Asistent_aischedule / Asistent_aischedulerun уже существуют."))
            return

        self.stdout.write("Создаём таблицы расписаний (применяем операции schedule.0001_initial)...")
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        loader.build_graph()

        migration = loader.disk_migrations.get(schedule_0001)
        if not migration:
            self.stdout.write(self.style.ERROR("Миграция schedule.0001_initial не найдена."))
            return

        # Состояние до применения 0001 (по зависимостям миграции)
        state = loader.project_state(
            nodes=[
                ("Asistent", "0073_alter_authornotification_options"),
                ("blog", "0032_post_video_preview"),
            ]
        )

        with connection.schema_editor() as schema_editor:
            for operation in migration.operations:
                new_state = state.clone()
                operation.state_forwards("schedule", new_state)
                operation.database_forwards("schedule", schema_editor, state, new_state)
                state = new_state

        self.stdout.write(self.style.SUCCESS("Таблицы созданы. Можно запускать: python manage.py migrate"))
