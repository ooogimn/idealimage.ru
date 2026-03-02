"""
Запуск генерации гороскопов вручную
"""
import os
import sys
import django

# Настройка Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')
django.setup()

from Asistent.schedule.tasks import run_specific_schedule
from Asistent.schedule.models import AISchedule

if __name__ == '__main__':
    print("=" * 70)
    print("[HOROSCOPE] ЗАПУСК ГЕНЕРАЦИИ ГОРОСКОПОВ")
    print("=" * 70)
    print()
    
    # Ищем активное расписание
    schedule = AISchedule.objects.filter(
        prompt_template__category='horoscope',
        is_active=True
    ).first()
    
    if not schedule:
        print("[ERROR] Активное расписание гороскопов не найдено!")
        sys.exit(1)
    
    print(f"[INFO] Расписание: {schedule.name} (ID: {schedule.id})")
    print(f"[INFO] Интервал между гороскопами: {schedule.payload_template.get('generation_delay', 20) if schedule.payload_template else 20} секунд")
    print()
    print("[START] Запуск генерации...")
    print("   Это может занять ~60 минут (12 гороскопов x 5 минут)")
    print()
    
    try:
        result = run_specific_schedule(schedule.id)
        
        print()
        print("=" * 70)
        print("[RESULTS] РЕЗУЛЬТАТЫ ГЕНЕРАЦИИ")
        print("=" * 70)
        print()
        print(f"Успешно: {result.get('success', False)}")
        print(f"Создано постов: {len(result.get('created_posts', []))}")
        print(f"Ошибок: {len(result.get('errors', []))}")
        print()
        
        if result.get('created_posts'):
            print("[OK] Созданные гороскопы:")
            for post in result.get('created_posts', [])[:12]:
                if hasattr(post, 'title'):
                    print(f"   - {post.title}")
                else:
                    print(f"   - Post ID: {post}")
        
        if result.get('errors'):
            print()
            print("[ERROR] Ошибки:")
            for error in result.get('errors', [])[:10]:
                print(f"   - {error}")
        
        print()
        print("=" * 70)
        
        if result.get('success'):
            print("[OK] Генерация завершена успешно!")
        else:
            print("[WARNING] Генерация завершена с ошибками")
        
    except Exception as e:
        print()
        print("[ERROR] Критическая ошибка:")
        print(f"   {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
