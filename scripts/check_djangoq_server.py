"""
Скрипт проверки статуса Celery на сервере.
"""
# LEGACY django_q 2026 migration: имя файла сохранено.
import os
import sys
import subprocess
from datetime import timedelta

import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings.production')
django.setup()

from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult


def check_celery_status():
    print("=" * 70)
    print("[CELERY] ПРОВЕРКА СТАТУСА")
    print("=" * 70)
    print()

    print("[1] Проверка процессов celery worker:")
    worker_processes = []
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
        worker_processes = [line for line in result.stdout.split('\n') if 'celery' in line and 'worker' in line]
        if worker_processes:
            print("   [OK] Найдены процессы celery worker")
        else:
            print("   [ERROR] Процессы celery worker не найдены")
    except Exception as exc:
        print(f"   [WARNING] Не удалось проверить процессы: {exc}")

    print()
    print("[2] Проверка расписаний Celery Beat:")
    schedules = PeriodicTask.objects.all()
    active_schedules = schedules.filter(enabled=True)
    print(f"   Всего расписаний: {schedules.count()}")
    print(f"   Активных: {active_schedules.count()}")

    print()
    print("[3] Проверка последних задач:")
    recent_tasks = TaskResult.objects.order_by('-date_created')[:10]
    if recent_tasks:
        for task in recent_tasks:
            print(f"   - {task.status}: {task.task_name} ({task.date_created})")
    else:
        print("   [WARNING] Нет задач в истории")

    print()
    print("[4] Проверка активности за последний час:")
    one_hour_ago = timezone.now() - timedelta(hours=1)
    recent_activity = TaskResult.objects.filter(date_created__gte=one_hour_ago).count()
    print(f"   Задач за час: {recent_activity}")

    print()
    print("=" * 70)
    print("[SUMMARY] ИТОГОВЫЙ СТАТУС")
    print("=" * 70)
    if worker_processes and recent_activity > 0:
        print("[OK] Celery работает нормально")
        return 0
    if worker_processes and recent_activity == 0:
        print("[WARNING] Worker запущен, но активности нет")
        return 1
    if (not worker_processes) and active_schedules.exists():
        print("[ERROR] Worker не запущен, но есть активные расписания")
        return 2
    print("[INFO] Worker не запущен, активных расписаний нет")
    return 0


if __name__ == '__main__':
    sys.exit(check_celery_status())
