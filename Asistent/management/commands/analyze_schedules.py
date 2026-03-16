"""
Команда для анализа состояния расписаний и фоновых задач (Celery).
"""
# LEGACY django_q 2026 migration: команда заменяет старую диагностику.
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult

from Asistent.models import AISchedule, AIScheduleRun


class Command(BaseCommand):
    help = 'Анализ текущего состояния расписаний и фоновых задач'

    def handle(self, *args, **options):
        now = timezone.now()

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('  📊 АНАЛИЗ РАСПИСАНИЙ И ЗАДАНИЙ'))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write('')

        self._analyze_ai_schedules(now)
        self._analyze_beat_schedules(now)
        self._analyze_recent_runs(now)
        self._analyze_celery_tasks(now)
        self._show_recommendations(now)

    def _analyze_ai_schedules(self, now):
        self.stdout.write(self.style.SUCCESS('[1/5] АНАЛИЗ AISCHEDULE'))
        self.stdout.write('-' * 80)
        all_schedules = AISchedule.objects.all()
        active_schedules = all_schedules.filter(is_active=True)
        inactive_schedules = all_schedules.filter(is_active=False)

        self.stdout.write(f'📋 Всего расписаний: {all_schedules.count()}')
        self.stdout.write(f'✅ Активных: {active_schedules.count()}')
        self.stdout.write(f'⏸️ Неактивных: {inactive_schedules.count()}')
        self.stdout.write('')

        for schedule in active_schedules.select_related('category', 'prompt_template').order_by('id')[:20]:
            status_icon = '🟢' if schedule.next_run and schedule.next_run > now else '🟡'
            self.stdout.write(f'  {status_icon} #{schedule.id} - {schedule.name}')
            self.stdout.write(f'     Частота: {schedule.get_posting_frequency_display()}')
            self.stdout.write(f'     Следующий запуск: {schedule.next_run or "Не установлено"}')
            self.stdout.write('')

    def _analyze_beat_schedules(self, now):
        self.stdout.write(self.style.SUCCESS('[2/5] АНАЛИЗ CELERY BEAT'))
        self.stdout.write('-' * 80)
        all_beat = PeriodicTask.objects.all()
        ai_beat = all_beat.filter(name__startswith='ai_schedule_')
        enabled_beat = ai_beat.filter(enabled=True)

        self.stdout.write(f'📋 Всего PeriodicTask: {all_beat.count()}')
        self.stdout.write(f'🤖 AI расписаний: {ai_beat.count()}')
        self.stdout.write(f'✅ Включенных AI расписаний: {enabled_beat.count()}')
        self.stdout.write('')

        for beat_task in enabled_beat.order_by('name')[:10]:
            self.stdout.write(f'  • {beat_task.name}: task={beat_task.task}')
            self.stdout.write(f'    last_run_at={beat_task.last_run_at or "—"}')
        self.stdout.write('')

    def _analyze_recent_runs(self, now):
        self.stdout.write(self.style.SUCCESS('[3/5] АНАЛИЗ ПОСЛЕДНИХ ЗАПУСКОВ'))
        self.stdout.write('-' * 80)
        recent_runs = AIScheduleRun.objects.select_related('schedule').order_by('-started_at')[:10]
        if not recent_runs:
            self.stdout.write('📭 Нет запусков')
            self.stdout.write('')
            return

        for run in recent_runs:
            self.stdout.write(f'  • {run.schedule.name}: {run.get_status_display()} ({run.started_at})')
        self.stdout.write('')

    def _analyze_celery_tasks(self, now):
        self.stdout.write(self.style.SUCCESS('[4/5] АНАЛИЗ CELERY TASK RESULTS'))
        self.stdout.write('-' * 80)
        hour_ago = now - timedelta(hours=1)

        active_tasks = TaskResult.objects.filter(status='STARTED')
        queued_tasks = TaskResult.objects.filter(status='PENDING')
        recent_tasks = TaskResult.objects.filter(date_created__gte=hour_ago)

        self.stdout.write(f'🔄 Активных задач: {active_tasks.count()}')
        self.stdout.write(f'⏳ В очереди: {queued_tasks.count()}')
        self.stdout.write(f'📊 За последний час: {recent_tasks.count()}')
        self.stdout.write(f'✅ Успешных: {recent_tasks.filter(status="SUCCESS").count()}')
        self.stdout.write(f'❌ Ошибок: {recent_tasks.filter(status="FAILURE").count()}')
        self.stdout.write('')

    def _show_recommendations(self, now):
        self.stdout.write(self.style.SUCCESS('[5/5] РЕКОМЕНДАЦИИ'))
        self.stdout.write('-' * 80)
        recommendations = []

        active_ai = AISchedule.objects.filter(is_active=True).count()
        active_beat = PeriodicTask.objects.filter(name__startswith='ai_schedule_', enabled=True).count()
        if active_ai != active_beat:
            recommendations.append(
                f'⚠️ Несоответствие: {active_ai} активных AISchedule, но {active_beat} активных PeriodicTask. '
                f'Запустите: python manage.py sync_schedules --force'
            )

        stale_tasks = TaskResult.objects.filter(
            status='PENDING',
            date_created__lt=now - timedelta(hours=2),
        ).count()
        if stale_tasks > 0:
            recommendations.append(f'⚠️ Найдено {stale_tasks} зависших PENDING задач старше 2 часов.')

        if recommendations:
            for idx, rec in enumerate(recommendations, 1):
                self.stdout.write(self.style.WARNING(f'{idx}. {rec}'))
        else:
            self.stdout.write(self.style.SUCCESS('✅ Все проверки пройдены!'))

        self.stdout.write('')
        self.stdout.write('=' * 80)
