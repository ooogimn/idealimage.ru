"""
Однократно: помечает миграции Asistent 0013 и 0014 как применённые в django_migrations,
чтобы устранить InconsistentMigrationHistory (blog.0022 применена раньше зависимости).
После запуска выполните: python manage.py migrate

Запуск: python manage.py fix_migration_history
"""
from django.core.management.base import BaseCommand
from django.db import connection

# Полная цепочка Asistent 0001–0014 (чтобы blog.0022 считалась корректной)
TO_FAKE = [
    ('Asistent', '0001_initial'),
    ('Asistent', '0002_commentmoderationcriteria'),
    ('Asistent', '0003_commentmoderationlog'),
    ('Asistent', '0004_remove_contenttask_approved_at_and_more'),
    ('Asistent', '0005_migrate_existing_tasks'),
    ('Asistent', '0006_add_video_fields_to_schedule'),
    ('Asistent', '0007_alter_aischedule_auto_publish_to_platforms_and_more'),
    ('Asistent', '0008_aischedule_mimic_author_style_and_more'),
    ('Asistent', '0009_titlevariant'),
    ('Asistent', '0010_add_generation_metrics'),
    ('Asistent', '0011_add_ai_agent_chat_models'),
    ('Asistent', '0012_update_bonus_formulas'),
    ('Asistent', '0013_add_smart_agent'),
    ('Asistent', '0014_add_performance_indexes'),
    ('Asistent', '0015_ai_chat_models'),  # AIConversation, AIMessage — нужны для donations.AIBonusCommand
]


class Command(BaseCommand):
    help = 'Пометить Asistent.0013 и 0014 как применённые (исправление истории миграций)'

    def handle(self, *args, **options):
        added = 0
        with connection.cursor() as cursor:
            for app, name in TO_FAKE:
                cursor.execute(
                    "SELECT 1 FROM django_migrations WHERE app = %s AND name = %s",
                    [app, name]
                )
                if cursor.fetchone():
                    self.stdout.write(f'  {app}.{name} уже в истории.')
                    continue
                cursor.execute(
                    "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, NOW())",
                    [app, name]
                )
                added += 1
                self.stdout.write(self.style.SUCCESS(f'  Добавлена запись: {app}.{name}'))
        connection.commit()
        if added:
            self.stdout.write(self.style.SUCCESS('Готово. Выполните: python manage.py migrate'))
        else:
            self.stdout.write(self.style.WARNING('Все записи уже были в истории.'))
