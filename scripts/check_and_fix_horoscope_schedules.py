"""
Скрипт для проверки и исправления расписаний гороскопов.
Проверяет настройки и синхронизацию с Celery Beat.
"""
import os
import sys
import django

# Настройка Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')
django.setup()

from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from Asistent.schedule.models import AISchedule
from Asistent.models import PromptTemplate
from datetime import time

def check_horoscope_schedules():
    """Проверяет расписания гороскопов"""
    print("=" * 70)
    print("[CHECK] ПРОВЕРКА РАСПИСАНИЙ ГОРОСКОПОВ")
    print("=" * 70)
    print()
    
    # Ищем расписания гороскопов
    schedules = AISchedule.objects.filter(
        prompt_template__category='horoscope'
    ).select_related('prompt_template', 'category')
    
    if not schedules.exists():
        print("[ERROR] Расписания гороскопов не найдены!")
        return None
    
    print(f"[INFO] Найдено расписаний: {schedules.count()}")
    print()
    
    issues = []
    active_schedules = []
    
    for schedule in schedules:
        schedule_name = schedule.name.encode('ascii', errors='ignore').decode('ascii') or f"Schedule {schedule.id}"
        print(f"[SCHEDULE] Расписание ID={schedule.id}: {schedule_name}")
        print(f"   Активно: {'[OK]' if schedule.is_active else '[NO]'}")
        print(f"   Стратегия: {schedule.strategy_type}")
        print(f"   Тип расписания: {schedule.schedule_kind}")
        print(f"   Время запуска: {schedule.scheduled_time}")
        print(f"   CRON: {schedule.cron_expression or '(не задано)'}")
        print(f"   Последний запуск: {schedule.last_run or 'Никогда'}")
        print(f"   Следующий запуск: {schedule.next_run or 'Не рассчитано'}")
        
        # Проверяем payload_template
        payload = schedule.payload_template or {}
        generation_delay = payload.get('generation_delay', 20)
        print(f"   Интервал между гороскопами: {generation_delay} секунд")
        
        # Проверяем Celery Beat расписание
        dq_name = f'ai_schedule_{schedule.id}'
        try:
            beat_schedule = PeriodicTask.objects.get(name=dq_name)
            print(
                f"   Celery Beat: [OK] Найдено (Task: {beat_schedule.task}, "
                f"Last run: {beat_schedule.last_run_at})"
            )
        except PeriodicTask.DoesNotExist:
            print(f"   Celery Beat: [ERROR] НЕ НАЙДЕНО!")
            issues.append(f"Расписание ID={schedule.id} не синхронизировано с Celery Beat")
        
        # Проверяем проблемы
        if not schedule.is_active:
            issues.append(f"Расписание ID={schedule.id} неактивно")
        elif schedule.scheduled_time is None and not schedule.cron_expression:
            issues.append(f"Расписание ID={schedule.id} не имеет времени запуска")
        
        if schedule.is_active:
            active_schedules.append(schedule)
        
        print()
    
    print("=" * 70)
    print("[RESULTS] РЕЗУЛЬТАТЫ ПРОВЕРКИ")
    print("=" * 70)
    
    if issues:
        print(f"[WARNING] Найдено проблем: {len(issues)}")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("[OK] Проблем не найдено!")
    
    print()
    return active_schedules


def fix_schedules():
    """Исправляет проблемы с расписаниями"""
    print("=" * 70)
    print("[FIX] ИСПРАВЛЕНИЕ РАСПИСАНИЙ")
    print("=" * 70)
    print()
    
    schedules = AISchedule.objects.filter(
        prompt_template__category='horoscope'
    )
    
    fixed_count = 0
    
    for schedule in schedules:
        fixed = False
        
        # Активируем если неактивно
        if not schedule.is_active:
            schedule.is_active = True
            fixed = True
            print(f"[OK] Активировано расписание ID={schedule.id}")
        
        # Устанавливаем время 10:00 если не задано
        if not schedule.scheduled_time and not schedule.cron_expression:
            schedule.scheduled_time = time(10, 0)
            schedule.schedule_kind = 'daily'
            fixed = True
            print(f"[OK] Установлено время 10:00 для расписания ID={schedule.id}")
        
        # Увеличиваем интервал до 5 минут если меньше
        payload = schedule.payload_template or {}
        current_delay = payload.get('generation_delay', 20)
        if current_delay < 300:
            payload['generation_delay'] = 300
            schedule.payload_template = payload
            fixed = True
            print(f"[OK] Увеличен интервал до 300 секунд для расписания ID={schedule.id}")
        
        if fixed:
            schedule.save()
            schedule.update_next_run()
            fixed_count += 1
    
    # Синхронизируем с Celery Beat
    if fixed_count > 0:
        print()
        print("[SYNC] Синхронизация с Celery Beat...")
        try:
            from django.core.management import call_command
            call_command('sync_schedules', '--force')
            print("[OK] Синхронизация завершена")
        except Exception as e:
            print(f"[ERROR] Ошибка синхронизации: {e}")
    
    print()
    print(f"[OK] Исправлено расписаний: {fixed_count}")
    return fixed_count


if __name__ == '__main__':
    print()
    print("[HOROSCOPE] ПРОВЕРКА И ИСПРАВЛЕНИЕ РАСПИСАНИЙ ГОРОСКОПОВ")
    print()
    
    # Проверка
    active_schedules = check_horoscope_schedules()
    
    if active_schedules:
        print()
        response = input("Исправить найденные проблемы? (y/n): ")
        if response.lower() == 'y':
            fix_schedules()
            print()
            print("[RE-CHECK] Повторная проверка...")
            print()
            check_horoscope_schedules()
    
    print()
    print("=" * 70)
    print("[OK] ПРОВЕРКА ЗАВЕРШЕНА")
    print("=" * 70)
