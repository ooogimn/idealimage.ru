#!/usr/bin/env python
"""
Скрипт для запуска генерации гороскопов без Овена.
"""
import os
import sys
import django

# Настройка Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')
django.setup()

from Asistent.schedule.models import AISchedule
from Asistent.schedule.tasks import run_specific_schedule

def run_horoscopes_without_aries():
    """Запускает генерацию гороскопов без Овена"""
    try:
        schedule = AISchedule.objects.get(id=1)
        
        # Добавляем Овена в список пропускаемых знаков
        payload = schedule.payload_template or {}
        payload['skip_signs'] = ['Овен']
        
        # Временно обновляем расписание
        old_payload = schedule.payload_template.copy() if schedule.payload_template else {}
        schedule.payload_template = payload
        schedule.save()
        
        print(f'🚀 Запуск генерации гороскопов без Овена...')
        print(f'   Пропускается: Овен')
        print(f'   Будет создано: 11 гороскопов')
        print()
        
        # Запускаем генерацию
        result = run_specific_schedule(1)
        
        # Восстанавливаем старое значение
        schedule.payload_template = old_payload
        schedule.save()
        
        print(f'\n=== РЕЗУЛЬТАТ ===')
        print(f'Success: {result.get("success")}')
        print(f'Status: {result.get("status")}')
        print(f'Created posts: {len(result.get("created_posts", []))}')
        print(f'Successful signs: {result.get("successful_signs", [])}')
        if result.get('failed_signs'):
            print(f'Failed signs: {result.get("failed_signs")}')
        if result.get('errors'):
            print(f'Errors: {len(result.get("errors", []))}')
        
        return result.get('success', False)
        
    except AISchedule.DoesNotExist:
        print(f'❌ Расписание ID=1 не найдено')
        return False
    except Exception as e:
        print(f'❌ Ошибка: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    run_horoscopes_without_aries()

