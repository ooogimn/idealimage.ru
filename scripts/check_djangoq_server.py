"""
Скрипт для проверки статуса Django-Q на сервере
Можно запускать через SSH или cron
"""
import os
import sys
import django

# Настройка Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings.production')
django.setup()

from django_q.models import Task, Schedule, OrmQ
from django.utils import timezone
from datetime import timedelta

def check_djangoq_status():
    """Проверяет статус Django-Q"""
    print("=" * 70)
    print("[DJANGO-Q] ПРОВЕРКА СТАТУСА")
    print("=" * 70)
    print()
    
    # 1. Проверка процессов через ps
    print("[1] Проверка процессов qcluster:")
    import subprocess
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=5
        )
        qcluster_processes = [line for line in result.stdout.split('\n') if 'qcluster' in line and 'manage.py' in line]
        
        if qcluster_processes:
            print("   [OK] Найдены процессы qcluster:")
            for proc in qcluster_processes:
                # Извлекаем PID
                parts = proc.split()
                if len(parts) > 1:
                    pid = parts[1]
                    print(f"      PID: {pid}")
        else:
            print("   [ERROR] Процессы qcluster не найдены!")
    except Exception as e:
        print(f"   [WARNING] Не удалось проверить процессы: {e}")
    
    print()
    
    # 2. Проверка расписаний
    print("[2] Проверка расписаний Django-Q:")
    schedules = Schedule.objects.all()
    active_schedules = schedules.filter(repeats__gt=0)
    
    print(f"   Всего расписаний: {schedules.count()}")
    print(f"   Активных: {active_schedules.count()}")
    
    if active_schedules.exists():
        print("   Ближайшие запуски:")
        for sched in active_schedules.order_by('next_run')[:5]:
            status = "OK" if sched.next_run else "NO TIME"
            print(f"      - {sched.name}: {sched.next_run} [{status}]")
    else:
        print("   [WARNING] Нет активных расписаний!")
    
    print()
    
    # 3. Проверка последних задач
    print("[3] Проверка последних задач:")
    recent_tasks = Task.objects.order_by('-started')[:10]
    
    if recent_tasks.exists():
        print(f"   Последние {recent_tasks.count()} задач:")
        for task in recent_tasks:
            status_icon = "[OK]" if task.success else "[ERROR]" if task.failed else "[RUN]"
            print(f"      {status_icon} {task.name}: {task.started} (успех: {task.success})")
    else:
        print("   [WARNING] Нет выполненных задач!")
    
    print()
    
    # 4. Проверка очереди
    print("[4] Проверка очереди задач:")
    queue_size = OrmQ.objects.count()
    print(f"   Задач в очереди: {queue_size}")
    
    if queue_size > 0:
        print("   [WARNING] Есть задачи в очереди - возможно qcluster не обрабатывает!")
    else:
        print("   [OK] Очередь пуста")
    
    print()
    
    # 5. Проверка активности (задачи за последний час)
    print("[5] Проверка активности за последний час:")
    one_hour_ago = timezone.now() - timedelta(hours=1)
    recent_activity = Task.objects.filter(started__gte=one_hour_ago).count()
    
    if recent_activity > 0:
        print(f"   [OK] Найдено {recent_activity} задач за последний час")
    else:
        print("   [WARNING] Нет активности за последний час!")
        print("   Возможно qcluster не работает или нет задач")
    
    print()
    
    # Итоговый статус
    print("=" * 70)
    print("[SUMMARY] ИТОГОВЫЙ СТАТУС")
    print("=" * 70)
    
    has_process = bool(qcluster_processes) if 'qcluster_processes' in locals() else False
    has_schedules = active_schedules.exists()
    has_recent_activity = recent_activity > 0
    
    if has_process and has_recent_activity:
        print("[OK] Django-Q работает нормально")
        return 0
    elif has_process and not has_recent_activity:
        print("[WARNING] Процесс запущен, но нет активности")
        print("   Возможно нет задач для выполнения")
        return 1
    elif not has_process and has_schedules:
        print("[ERROR] Django-Q НЕ ЗАПУЩЕН, но есть активные расписания!")
        print("   Запустите: python manage.py qcluster")
        return 2
    else:
        print("[INFO] Django-Q не запущен, но нет активных расписаний")
        return 0

if __name__ == '__main__':
    exit_code = check_djangoq_status()
    sys.exit(exit_code)
