"""
Синхронизация AISchedule с Celery Beat PeriodicTask.
"""
# LEGACY django_q 2026 migration: имя команды сохранено.
import json
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from Asistent.models import AISchedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Синхронизация расписаний AI с Celery Beat'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Пересоздать все расписания',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)

        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  🔄 СИНХРОНИЗАЦИЯ РАСПИСАНИЙ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')

        ai_schedules = AISchedule.objects.filter(is_active=True)
        self.stdout.write(f'📋 Найдено активных расписаний AI: {ai_schedules.count()}')
        self.stdout.write('')

        created_count = 0
        updated_count = 0
        deleted_count = 0

        for ai_schedule in ai_schedules:
            task_name = f'ai_schedule_{ai_schedule.id}'

            if not ai_schedule.next_run or ai_schedule.next_run < timezone.now():
                ai_schedule.update_next_run(commit=True)

            task_defaults = self._build_periodic_defaults(ai_schedule)

            existing = PeriodicTask.objects.filter(name=task_name).first()
            if existing and force:
                existing.delete()
                existing = None

            if existing:
                for key, value in task_defaults.items():
                    setattr(existing, key, value)
                existing.save()
                updated_count += 1
                self.stdout.write(self.style.SUCCESS(f'  ✓ Обновлено: "{ai_schedule.name}"'))
            else:
                PeriodicTask.objects.create(name=task_name, **task_defaults)
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  ✨ Создано: "{ai_schedule.name}"'))

        self.stdout.write('')
        self.stdout.write('🧹 Очистка неактивных расписаний...')
        active_ids = set(ai_schedules.values_list('id', flat=True))
        beat_schedules = PeriodicTask.objects.filter(name__startswith='ai_schedule_')
        for beat_task in beat_schedules:
            try:
                schedule_id = int(beat_task.name.replace('ai_schedule_', ''))
            except ValueError:
                continue
            if schedule_id not in active_ids:
                beat_task.delete()
                deleted_count += 1
                self.stdout.write(self.style.WARNING(f'  🗑️ Удалено: {beat_task.name}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  ✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write(f'✨ Создано новых: {created_count}')
        self.stdout.write(f'♻️ Обновлено: {updated_count}')
        self.stdout.write(f'🗑️ Удалено: {deleted_count}')
        self.stdout.write('')
        total_active = PeriodicTask.objects.filter(name__startswith='ai_schedule_', enabled=True).count()
        self.stdout.write(f'📊 Активных расписаний в Celery Beat: {total_active}')
        self.stdout.write('')

    def _build_periodic_defaults(self, schedule):
        interval = None
        crontab = None

        if schedule.cron_expression:
            parts = schedule.cron_expression.split()
            if len(parts) == 5:
                crontab, _ = CrontabSchedule.objects.get_or_create(
                    minute=parts[0],
                    hour=parts[1],
                    day_of_month=parts[2],
                    month_of_year=parts[3],
                    day_of_week=parts[4],
                )
        elif schedule.interval_minutes:
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=max(1, schedule.interval_minutes),
                period=IntervalSchedule.MINUTES,
            )
        else:
            run_time = schedule.scheduled_time or timezone.now().time().replace(second=0, microsecond=0)
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=str(run_time.minute),
                hour=str(run_time.hour),
                day_of_month='*',
                month_of_year='*',
                day_of_week='*',
            )

        return {
            'task': 'Asistent.tasks.run_specific_schedule',
            'args': json.dumps([schedule.id]),
            'kwargs': '{}',
            'enabled': schedule.is_active,
            'description': f'Auto-synced for AISchedule #{schedule.id}',
            'start_time': schedule.next_run,
            'one_off': False,
            'interval': interval,
            'crontab': crontab,
        }
