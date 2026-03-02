"""
Celery — конфигурация для проекта IdealImage.ru
Заменяет Django-Q для фоновых задач.
Брокер: Redis. Хранение результатов: Redis (django-celery-results).
"""
import os
from celery import Celery

# Используем production по умолчанию, development переопределит через .env
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings.production')

app = Celery('idealimage')

# Считываем настройки из settings.py с префиксом CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически регистрируем задачи из tasks.py всех INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
