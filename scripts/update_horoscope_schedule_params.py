#!/usr/bin/env python
"""
Скрипт для обновления параметров расписания гороскопов.
Увеличивает задержки для предотвращения ошибок 429.
"""
import os
import sys
import django

# Настройка Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')
django.setup()

from Asistent.schedule.models import AISchedule

def update_horoscope_schedule():
    """Обновляет параметры расписания гороскопов"""
    try:
        schedule = AISchedule.objects.get(id=1)
        
        payload = schedule.payload_template or {}
        payload['generation_delay'] = 20  # Увеличиваем до 20 секунд
        payload['retry_delay'] = 60  # Увеличиваем до 60 секунд
        payload['check_cooldown'] = True  # Включаем проверку cooldown
        
        schedule.payload_template = payload
        schedule.save()
        
        print(f'✅ Обновлено расписание ID={schedule.id}: {schedule.name}')
        print(f'   generation_delay: {payload["generation_delay"]}с')
        print(f'   retry_delay: {payload["retry_delay"]}с')
        print(f'   check_cooldown: {payload["check_cooldown"]}')
        
        return True
    except AISchedule.DoesNotExist:
        print(f'❌ Расписание ID=1 не найдено')
        return False
    except Exception as e:
        print(f'❌ Ошибка: {e}')
        return False

if __name__ == '__main__':
    update_horoscope_schedule()

