"""
Команда для обновления путей функций в Celery Beat PeriodicTask.
"""
# LEGACY django_q 2026 migration: оставлена для безопасной миграции.
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Обновление путей функций в Celery Beat на новый путь'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать что будет обновлено без реального обновления'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  🔄 ОБНОВЛЕНИЕ ПУТЕЙ DJANGO-Q SCHEDULE'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')

        # Находим все задачи со старым путем
        old_path = 'Asistent.tasks.run_specific_schedule'
        new_path = 'Asistent.schedule.tasks.run_specific_schedule'
        
        old_schedules = PeriodicTask.objects.filter(task=old_path)
        count = old_schedules.count()
        
        self.stdout.write(f'📋 Найдено расписаний со старым путем: {count}')
        self.stdout.write('')
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('✅ Все расписания уже используют новый путь!'))
            return
        
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 РЕЖИМ ПРОСМОТРА (dry-run):'))
            self.stdout.write('')
            for schedule in old_schedules:
                self.stdout.write(f'  - {schedule.name} (ID: {schedule.id})')
                self.stdout.write(f'    Старый путь: {schedule.func}')
                self.stdout.write(f'    Новый путь: {new_path}')
                self.stdout.write('')
            self.stdout.write(self.style.WARNING(f'Будет обновлено: {count} расписаний'))
        else:
            # Обновляем все расписания
            updated = old_schedules.update(task=new_path)
            
            self.stdout.write(self.style.SUCCESS(f'✅ Обновлено расписаний: {updated}'))
            self.stdout.write('')
            
            # Показываем обновленные расписания
            for schedule in PeriodicTask.objects.filter(task=new_path):
                self.stdout.write(f'  ✓ {schedule.name} (ID: {schedule.id})')
            
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('🎉 Обновление завершено!'))
            self.stdout.write('')
            self.stdout.write('💡 Рекомендация: Перезапустите celery worker/beat для применения изменений')

