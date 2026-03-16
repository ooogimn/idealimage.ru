"""
Скрипт для остановки текущей генерации гороскопов в Celery.
"""
import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings.production')
django.setup()

from celery.result import AsyncResult
from django.core.cache import cache
from django.utils import timezone
from django_celery_results.models import TaskResult

from Asistent.schedule.models import AISchedule


def stop_current_horoscope_generation():
    print("=" * 70)
    print("[STOP HOROSCOPE] ОСТАНОВКА ТЕКУЩЕЙ ГЕНЕРАЦИИ ГОРОСКОПОВ")
    print("=" * 70)
    print()

    print("[1] Поиск pending/start задач, связанных с horoscope...")
    candidate_tasks = TaskResult.objects.filter(
        status__in=['PENDING', 'STARTED'],
        task_name__icontains='horoscope',
    ).order_by('-date_created')
    print(f"   Найдено задач: {candidate_tasks.count()}")

    revoked = 0
    for task in candidate_tasks:
        try:
            AsyncResult(task.task_id).revoke(terminate=False)
            task.status = 'REVOKED'
            task.save(update_fields=['status'])
            revoked += 1
            print(f"   - revoke: {task.task_id}")
        except Exception as exc:
            print(f"   [WARNING] revoke failed for {task.task_id}: {exc}")

    print(f"   [OK] Отозвано задач: {revoked}")
    print()

    print("[2] Очистка кэша приоритета гороскопов...")
    today_str = timezone.now().date().isoformat()
    cache.delete(f"horoscope_generation_active:{today_str}")
    cache.delete("horoscope_generation_priority")
    print("   [OK] Кэш очищен")
    print()

    print("[3] Проверка активного расписания...")
    schedule = AISchedule.objects.filter(prompt_template__category='horoscope', is_active=True).first()
    if schedule:
        print(f"   [OK] Расписание: {schedule.name} (ID={schedule.id})")
        print(f"   Следующий запуск: {schedule.next_run}")
    else:
        print("   [WARNING] Активное расписание гороскопов не найдено")

    print()
    print("=" * 70)
    print("[OK] Операция завершена")
    print("=" * 70)


if __name__ == '__main__':
    stop_current_horoscope_generation()
