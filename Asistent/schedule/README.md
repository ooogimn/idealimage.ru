# 📅 Schedule - Автономная система управления расписаниями

## 🎯 Описание

`schedule` - это автономное Django-приложение для управления расписаниями и задачами AI-генерации контента. Приложение можно легко перенести в любой другой Django-проект.

## ✨ Возможности

- ✅ Различные типы расписаний: ежедневные, еженедельные, по интервалам, по CRON
- ✅ Несколько стратегий выполнения: промпт-шаблоны, системные задачи, ручной режим
- ✅ Автоматическая синхронизация с Django-Q через signals
- ✅ Приоритизация задач (например, гороскопы имеют высокий приоритет)
- ✅ Журналирование всех запусков с детальной статистикой
- ✅ Dependency Injection для работы с внешними сервисами
- ✅ Полная независимость от основного приложения

## 📦 Структура приложения

```
schedule/
├── __init__.py              # Экспорты модуля
├── apps.py                  # Конфигурация Django-приложения
├── models.py                # Модели AISchedule и AIScheduleRun
├── signals.py               # Автосинхронизация с Django-Q
├── tasks.py                 # Задачи для выполнения расписаний
├── strategies.py            # Стратегии выполнения
├── services.py              # Сервисы генерации контента
├── context.py               # Контекст выполнения
├── logger.py                # Логирование запусков
├── presets.py               # Предустановленные расписания
├── interfaces.py            # Интерфейсы для DI
└── README.md                # Документация
```

## 🚀 Установка в новом проекте

### 1. Скопировать папку `schedule/`

```bash
cp -r Asistent/schedule/ /path/to/your/project/
```

### 2. Добавить в `INSTALLED_APPS`

```python
# settings.py
INSTALLED_APPS = [
    # ...
    'schedule',  # или 'yourapp.schedule' если скопировали внутрь приложения
    'django_q',  # Обязательно!
]
```

### 3. Настроить Django-Q

```python
# settings.py
Q_CLUSTER = {
    'name': 'schedules',
    'workers': 4,
    'recycle': 500,
    'timeout': 300,
    'compress': True,
    'save_limit': 250,
    'queue_limit': 500,
    'cpu_affinity': 1,
    'label': 'Django Q',
    'orm': 'default',  # Используем Django ORM вместо Redis
}
```

### 4. Применить миграции

```bash
python manage.py migrate
```

### 5. Настроить зависимости (опционально)

Если у вас свои реализации сервисов (AI, SEO и т.д.), зарегистрируйте их через ServiceLocator:

```python
# yourapp/apps.py
from schedule.interfaces import ServiceLocator
from yourapp.services import YourAIService, YourSEOService

class YourAppConfig(AppConfig):
    def ready(self):
        ServiceLocator.register('content_generator', YourAIService())
        ServiceLocator.register('seo_optimizer', YourSEOService())
```

## 🔧 Использование

### Создание расписания через код

```python
from schedule.models import AISchedule
from datetime import time

schedule = AISchedule.objects.create(
    name="Ежедневные статьи о технологиях",
    strategy_type='prompt',
    schedule_kind='daily',
    scheduled_time=time(8, 0),  # 08:00
    is_active=True,
    articles_per_run=3,
    tags="технологии, AI",
)
```

### Ручной запуск расписания

```python
from schedule.tasks import run_specific_schedule

result = run_specific_schedule(schedule_id=1)
print(result)  # {'success': True, 'created_count': 3, ...}
```

### Использование стратегий напрямую

```python
from schedule.strategies import PromptScheduleStrategy
from schedule.models import AISchedule

schedule = AISchedule.objects.get(id=1)
strategy = PromptScheduleStrategy(schedule)
result = strategy.execute()
```

## 🎨 Кастомизация

### Создание собственной стратегии

```python
from schedule.strategies import ScheduleStrategy
from schedule.context import ScheduleContext

class CustomStrategy(ScheduleStrategy):
    strategy_type = 'custom'
    
    def _execute(self, context: ScheduleContext) -> dict:
        # Ваша логика
        return {
            'status': 'success',
            'created_count': 5,
            'errors': [],
        }

# Регистрация стратегии
from schedule.tasks import STRATEGY_MAP
STRATEGY_MAP['custom'] = CustomStrategy
```

### Подключение своего AI-генератора

```python
from schedule.interfaces import ContentGeneratorInterface, ServiceLocator

class MyAIGenerator(ContentGeneratorInterface):
    def chat(self, message: str, **kwargs) -> str:
        # Ваша реализация
        return "Generated content"
    
    def get_usage_stats(self) -> dict:
        return {'tokens': 100}

# Регистрация
ServiceLocator.register('content_generator', MyAIGenerator())
```

## 📊 Мониторинг

### Просмотр истории запусков

```python
from schedule.models import AIScheduleRun

# Последние 10 запусков
recent_runs = AIScheduleRun.objects.select_related('schedule').order_by('-started_at')[:10]

for run in recent_runs:
    print(f"{run.schedule.name}: {run.status} ({run.created_count} объектов)")
```

### Статистика по расписанию

```python
schedule = AISchedule.objects.get(id=1)
runs = schedule.runs.all()

total = runs.count()
success = runs.filter(status='success').count()
failed = runs.filter(status='failed').count()

print(f"Всего: {total}, Успешно: {success}, Ошибок: {failed}")
```

## 🔒 Приоритизация задач

Приложение поддерживает приоритизацию через cache:

```python
from django.core.cache import cache

# Установить высокий приоритет для задачи
cache.set('task_priority:horoscope', True, timeout=300)

# Проверить приоритет
if cache.get('task_priority:horoscope'):
    # Запустить приоритетную задачу
    pass
```

## 🐛 Отладка

### Логирование

Все действия логируются в стандартный логгер Django:

```python
import logging
logger = logging.getLogger('schedule')
logger.setLevel(logging.DEBUG)
```

### Проверка синхронизации с Django-Q

```bash
python manage.py shell
```

```python
from django_q.models import Schedule
from schedule.models import AISchedule

# Проверка соответствия
ai_schedules = AISchedule.objects.filter(is_active=True).count()
dq_schedules = Schedule.objects.filter(name__startswith='ai_schedule_').count()

print(f"AISchedule активных: {ai_schedules}")
print(f"Django-Q задач: {dq_schedules}")
```

## 🔄 Миграция данных

При переносе из старого проекта:

1. Модели используют старые имена таблиц (`db_table = 'Asistent_aischedule'`)
2. Данные автоматически будут доступны
3. Обновите пути в Django-Q Schedule:

```python
from django_q.models import Schedule
Schedule.objects.filter(func='Asistent.tasks.run_specific_schedule').update(
    func='schedule.tasks.run_specific_schedule'
)
```

## 📚 API Reference

### Модели

#### AISchedule
- `name` - Название расписания
- `strategy_type` - Тип стратегии (prompt, system, manual, pipeline)
- `schedule_kind` - Тип расписания (daily, weekly, interval, cron)
- `is_active` - Активно ли расписание
- `next_run` - Время следующего запуска
- `calculate_next_run()` - Вычисляет следующий запуск
- `update_next_run()` - Обновляет next_run

#### AIScheduleRun
- `schedule` - Связь с AISchedule
- `status` - Статус (running, success, failed, partial)
- `created_count` - Количество созданных объектов
- `errors` - Список ошибок
- `duration` - Длительность выполнения

### Функции

#### run_specific_schedule(schedule_id: int)
Запускает расписание по ID. Возвращает dict с результатом.

#### calculate_next_run_delta(frequency: str)
Вычисляет интервал до следующего запуска.

## 🤝 Контрибьюция

При улучшении приложения:
1. Сохраняйте обратную совместимость
2. Документируйте изменения
3. Добавляйте тесты
4. Следуйте стилю кода проекта

## 📄 Лицензия

Используется в рамках проекта IdealImage.ru

## 🔗 Связь

При возникновении вопросов обращайтесь к разработчикам проекта.

