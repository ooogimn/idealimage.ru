"""
Команда для синхронизации AISchedule с Django-Q Schedule
Создает периодические задачи в Django-Q на основе активных расписаний
Использует ту же логику, что и signals.py для правильной синхронизации CRON расписаний
"""
from django.core.management.base import BaseCommand
from django_q.models import Schedule
from Asistent.models import AISchedule  # Через __getattr__
from django.utils import timezone
from Asistent.schedule.signals import _build_django_q_schedule, _apply_schedule_config, _cleanup_schedule_kwargs
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Синхронизация расписаний AI с Django-Q Schedule'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Пересоздать все расписания'
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  🔄 СИНХРОНИЗАЦИЯ РАСПИСАНИЙ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')

        # Получаем активные расписания AI
        ai_schedules = AISchedule.objects.filter(is_active=True)
        self.stdout.write(f'📋 Найдено активных расписаний AI: {ai_schedules.count()}')
        self.stdout.write('')

        created_count = 0
        updated_count = 0
        deleted_count = 0

        # Проходим по всем активным расписаниям
        for ai_schedule in ai_schedules:
            schedule_name = f'ai_schedule_{ai_schedule.id}'
            
            # Обновляем next_run если он устарел
            if not ai_schedule.next_run or ai_schedule.next_run < timezone.now():
                ai_schedule.update_next_run(commit=True)
                self.stdout.write(self.style.WARNING(
                    f'  🔄 Обновлён next_run для "{ai_schedule.name}": {ai_schedule.next_run}'
                ))
            
            # Используем ту же логику, что и signals.py
            config = _build_django_q_schedule(ai_schedule)
            if not config:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠️ Пропущено расписание "{ai_schedule.name}" - не удалось построить конфигурацию'
                ))
                continue

            # Проверяем существует ли Schedule в Django-Q
            try:
                dq_schedule = Schedule.objects.get(name=schedule_name)
                
                if force:
                    # Удаляем и создаем заново
                    dq_schedule.delete()
                    dq_schedule = Schedule.objects.create(**_cleanup_schedule_kwargs(config))
                    # Проверяем и исправляем next_run если Django-Q пересчитал неправильно
                    if config['schedule_type'] == Schedule.CRON and config.get('next_run'):
                        expected_next_run = config['next_run']
                        if dq_schedule.next_run and abs((dq_schedule.next_run - expected_next_run).total_seconds()) > 3600:
                            dq_schedule.next_run = expected_next_run
                            dq_schedule.save(update_fields=['next_run'])
                            self.stdout.write(self.style.WARNING(
                                f'  🔧 Исправлен next_run: {dq_schedule.next_run}'
                            ))
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ Пересоздано: "{ai_schedule.name}" [{config.get("description", "")}]'
                    ))
                else:
                    # Обновляем существующее используя ту же логику, что и signals
                    _apply_schedule_config(dq_schedule, config)
                    updated_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ Обновлено: "{ai_schedule.name}" [{config.get("description", "")}]'
                    ))
                    
            except Schedule.DoesNotExist:
                # Создаем новое расписание
                dq_schedule = Schedule.objects.create(**_cleanup_schedule_kwargs(config))
                # Проверяем и исправляем next_run если Django-Q пересчитал неправильно
                if config['schedule_type'] == Schedule.CRON and config.get('next_run'):
                    expected_next_run = config['next_run']
                    if dq_schedule.next_run and abs((dq_schedule.next_run - expected_next_run).total_seconds()) > 3600:
                        dq_schedule.next_run = expected_next_run
                        dq_schedule.save(update_fields=['next_run'])
                        self.stdout.write(self.style.WARNING(
                            f'  🔧 Исправлен next_run: {dq_schedule.next_run}'
                        ))
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  ✨ Создано: "{ai_schedule.name}" [{config.get("description", "")}]'
                ))

        # Удаляем расписания для неактивных AISchedule
        self.stdout.write('')
        self.stdout.write('🧹 Очистка неактивных расписаний...')
        
        all_dq_schedules = Schedule.objects.filter(name__startswith='ai_schedule_')
        for dq_schedule in all_dq_schedules:
            # Извлекаем ID из имени
            try:
                schedule_id = int(dq_schedule.name.replace('ai_schedule_', ''))
                
                # Проверяем существует ли и активен ли AISchedule
                try:
                    ai_schedule = AISchedule.objects.get(id=schedule_id, is_active=True)
                except AISchedule.DoesNotExist:
                    # AISchedule не существует или неактивен - удаляем
                    dq_schedule.delete()
                    deleted_count += 1
                    self.stdout.write(self.style.WARNING(
                        f'  🗑️ Удалено: {dq_schedule.name} (расписание неактивно или удалено)'
                    ))
            except (ValueError, AttributeError):
                # Не наше расписание
                pass

        # Итоговая статистика
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  ✅ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write(f'✨ Создано новых: {created_count}')
        self.stdout.write(f'♻️ Обновлено: {updated_count}')
        self.stdout.write(f'🗑️ Удалено: {deleted_count}')
        self.stdout.write('')
        
        total_active = Schedule.objects.filter(
            name__startswith='ai_schedule_',
            repeats=-1  # -1 означает бесконечные повторения
        ).count()
        self.stdout.write(f'📊 Активных расписаний в Django-Q: {total_active}')
        self.stdout.write('')


