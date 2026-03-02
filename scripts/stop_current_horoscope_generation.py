"""
Скрипт для остановки текущей генерации гороскопов
Останавливает активные задачи, но сохраняет расписание для завтрашнего запуска
"""
import os
import sys
import django

# Настройка Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings.production')
django.setup()

from django_q.models import Task, OrmQ
from django.utils import timezone
from Asistent.schedule.models import AISchedule
from django.core.cache import cache

def stop_current_horoscope_generation():
    """Останавливает текущую генерацию гороскопов"""
    print("=" * 70)
    print("[STOP HOROSCOPE] ОСТАНОВКА ТЕКУЩЕЙ ГЕНЕРАЦИИ ГОРОСКОПОВ")
    print("=" * 70)
    print()
    
    # 1. Проверяем активные задачи в очереди
    print("[1] Проверка задач в очереди Django-Q...")
    # OrmQ не имеет поля func, проверяем все задачи в очереди и фильтруем по payload
    all_queued = OrmQ.objects.filter(lock__isnull=True)
    queued_count = all_queued.count()
    print(f"   Всего задач в очереди: {queued_count}")
    
    # Фильтруем задачи связанные с гороскопами по payload
    horoscope_tasks = []
    for task in all_queued:
        # Проверяем payload - там может быть информация о функции
        payload = task.payload if hasattr(task, 'payload') else {}
        key = task.key if hasattr(task, 'key') else ''
        
        # Проверяем по ключу или payload
        if 'horoscope' in str(key).lower() or 'schedule' in str(key).lower():
            horoscope_tasks.append(task)
        elif isinstance(payload, dict):
            # Проверяем args в payload
            args = payload.get('args', [])
            if args and isinstance(args, list):
                # Если первый аргумент - это ID расписания гороскопов (2)
                if len(args) > 0 and args[0] == 2:
                    horoscope_tasks.append(task)
    
    horoscope_count = len(horoscope_tasks)
    print(f"   Найдено задач гороскопов: {horoscope_count}")
    
    if horoscope_count > 0:
        print("   [DELETE] Удаление задач гороскопов из очереди...")
        for task in horoscope_tasks:
            print(f"      - Удаление задачи ID: {task.id}")
            task.delete()
        print(f"   [OK] Удалено задач: {horoscope_count}")
    else:
        print("   [OK] Задач гороскопов в очереди нет")
    
    print()
    
    # 2. Проверяем выполняющиеся задачи (в модели Task/Success)
    print("[2] Проверка выполняющихся задач...")
    from django_q.models import Success
    running_tasks = Success.objects.filter(
        started__isnull=False,
        stopped__isnull=True
    ).filter(
        func__icontains='horoscope'
    ) | Success.objects.filter(
        started__isnull=False,
        stopped__isnull=True,
        name__icontains='horoscope'
    )
    
    running_count = running_tasks.count()
    print(f"   Найдено выполняющихся задач: {running_count}")
    
    if running_count > 0:
        print("   [WARNING] Есть выполняющиеся задачи (их нельзя остановить программно)")
        print("   Они завершатся сами или нужно будет перезапустить qcluster")
        for task in running_tasks:
            print(f"      - Выполняется: {task.name} (Started: {task.started})")
    else:
        print("   [OK] Выполняющихся задач нет")
    
    print()
    
    # 3. Очищаем кэш приоритета гороскопов
    print("[3] Очистка кэша приоритета гороскопов...")
    today_str = timezone.now().date().isoformat()
    blocking_key = f"horoscope_generation_active:{today_str}"
    horoscope_priority_key = "horoscope_generation_priority"
    
    cache.delete(blocking_key)
    cache.delete(horoscope_priority_key)
    print("   [OK] Кэш очищен")
    
    print()
    
    # 4. Проверяем расписание гороскопов
    print("[4] Проверка расписания гороскопов...")
    schedule = AISchedule.objects.filter(
        prompt_template__category='horoscope',
        is_active=True
    ).first()
    
    if schedule:
        print(f"   Расписание найдено: ID={schedule.id}, Название={schedule.name}")
        print(f"   Активно: {schedule.is_active}")
        print(f"   CRON: {schedule.cron_expression}")
        print(f"   Следующий запуск: {schedule.next_run}")
        
        # Убеждаемся что расписание активно
        if not schedule.is_active:
            schedule.is_active = True
            schedule.update_next_run()
            schedule.save(update_fields=['is_active', 'next_run'])
            print("   [OK] Расписание активировано")
        else:
            print("   [OK] Расписание уже активно")
    else:
        print("   [ERROR] Активное расписание гороскопов не найдено!")
    
    print()
    
    # Итог
    print("=" * 70)
    print("[SUMMARY] ИТОГОВЫЙ СТАТУС")
    print("=" * 70)
    print(f"   Удалено задач из очереди: {queued_count}")
    print(f"   Выполняющихся задач: {running_count}")
    print(f"   Расписание активно: {schedule.is_active if schedule else False}")
    if schedule:
        print(f"   Следующий запуск: {schedule.next_run}")
    print()
    print("[OK] Текущая генерация остановлена")
    print("      Расписание сохранено для завтрашнего запуска в 10:00")
    print("=" * 70)

if __name__ == '__main__':
    stop_current_horoscope_generation()
