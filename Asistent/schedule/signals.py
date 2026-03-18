"""
Сигналы для автоматической синхронизации расписаний с Celery Beat.
Создаёт, обновляет и удаляет периодические задачи в Celery при изменении AISchedule.
"""
from datetime import time as dtime

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django_celery_beat.models import PeriodicTask, CrontabSchedule, IntervalSchedule
from django.utils import timezone
import json
import logging

from .models import AISchedule

logger = logging.getLogger(__name__)


@receiver(post_save, sender=AISchedule)
def sync_ai_schedule_on_save(sender, instance, created, **kwargs):
    """
    Автоматически создает/обновляет PeriodicTask в Celery Beat
    при сохранении AISchedule
    """
    task_name = f'ai_schedule_{instance.id}'
    
    if not instance.is_active:
        # Если расписание неактивно - удаляем из Celery Beat
        try:
            periodic_task = PeriodicTask.objects.get(name=task_name)
            periodic_task.delete()
            logger.info(f"🗑️ Удалено неактивное расписание {task_name}")
        except PeriodicTask.DoesNotExist:
            pass
        return
    
    # Создаем или обновляем расписание в Celery Beat
    schedule = _build_celery_schedule(instance)
    if not schedule:
        logger.warning("⚠️ Не удалось построить расписание для %s", instance)
        return

    try:
        periodic_task = PeriodicTask.objects.get(name=task_name)
        # Обновляем существующую задачу
        periodic_task.task = 'Asistent.schedule.tasks.run_specific_schedule'
        periodic_task.args = json.dumps([])
        periodic_task.kwargs = json.dumps({'schedule_id': instance.id})
        periodic_task.enabled = True

        # Обновляем расписание — schedule это dict {'interval': obj} или {'crontab': obj}
        if 'crontab' in schedule:
            periodic_task.crontab = schedule['crontab']
            periodic_task.interval = None
        elif 'interval' in schedule:
            periodic_task.interval = schedule['interval']
            periodic_task.crontab = None

        periodic_task.save()
        logger.info("♻️ Обновлено расписание %s", instance.name)

    except PeriodicTask.DoesNotExist:
        # Создаём новое расписание
        periodic_task = PeriodicTask.objects.create(
            name=task_name,
            task='Asistent.schedule.tasks.run_specific_schedule',
            args=json.dumps([]),
            kwargs=json.dumps({'schedule_id': instance.id}),
            **schedule
        )
        logger.info("✨ Создано расписание %s", instance.name)


@receiver(post_delete, sender=AISchedule)
def delete_schedule_on_ai_schedule_delete(sender, instance, **kwargs):
    """
    Автоматически удаляет PeriodicTask из Celery Beat
    при удалении AISchedule
    """
    task_name = f'ai_schedule_{instance.id}'
    try:
        periodic_task = PeriodicTask.objects.get(name=task_name)
        periodic_task.delete()
        logger.info(f"🗑️ Удалено расписание {task_name} после удаления AISchedule")
    except PeriodicTask.DoesNotExist:
        pass


# ============================================================================
# Вспомогательные функции для построения Celery Beat Schedule
# ============================================================================

def get_interval_minutes(frequency):
    """Преобразует частоту в минуты"""
    frequency_map = {
        'hourly': 60,
        'every_2_hours': 120,
        'every_3_hours': 180,
        'every_4_hours': 240,
        'every_6_hours': 360,
        'every_8_hours': 480,
        'every_12_hours': 720,
        'daily': 1440,
        'twice_daily': 720,
        'weekly': 10080,
    }
    return frequency_map.get(frequency)


def _default_time():
    """Возвращает время по умолчанию для запуска расписания"""
    return dtime(hour=8, minute=0)


def _build_celery_schedule(instance):
    """Формирует расписание для Celery Beat с учётом schedule_kind."""
    kind = (instance.schedule_kind or 'daily').lower()
    
    if kind == 'interval':
        minutes = instance.interval_minutes or get_interval_minutes(instance.posting_frequency) or 60
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=minutes,
            period=IntervalSchedule.MINUTES,
        )
        return {'interval': schedule}
    else:
        # CRON расписание
        cron_expr = _resolve_cron_expression(instance, kind)
        if not cron_expr:
            return None
        
        # Парсим CRON: минута час день_месяца месяц день_недели
        parts = cron_expr.split()
        if len(parts) >= 5:
            minute, hour, day_of_month, month, day_of_week = parts[0], parts[1], parts[2], parts[3], parts[4]
        else:
            # По умолчанию ежедневно
            minute = instance.scheduled_time.minute if instance.scheduled_time else 0
            hour = instance.scheduled_time.hour if instance.scheduled_time else 8
            day_of_month = '*'
            month = '*'
            day_of_week = '*'
        
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month_of_year=month,
            day_of_week=day_of_week,
        )
        return {'crontab': schedule}


def _resolve_cron_expression(instance, kind):
    """Формирует CRON-выражение в зависимости от типа расписания"""
    time_point = instance.scheduled_time or _default_time()
    minute, hour = time_point.minute, time_point.hour

    if kind == 'cron':
        cron_expr = (instance.cron_expression or '').strip()
        if cron_expr:
            return cron_expr
        return f"{minute} {hour} * * *"
    if kind == 'weekly':
        weekday = instance.weekday if instance.weekday is not None else 0
        return f"{minute} {hour} * * {weekday}"
    # daily и остальные по умолчанию
    return f"{minute} {hour} * * *"

