"""
Тестовая команда для проверки работы Celery.
"""
# LEGACY django_q 2026 migration: имя команды сохранено.
from django.core.management.base import BaseCommand
from django_celery_results.models import TaskResult
from Asistent.tasks import async_task
import time


class Command(BaseCommand):
    help = 'Тестирование Celery worker/results'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('  ТЕСТИРОВАНИЕ Celery'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        
        # Тест 1: Проверка подключения к БД
        self.stdout.write('[1/4] Проверка подключения к БД результатов Celery...')
        try:
            task_count = TaskResult.objects.count()
            self.stdout.write(self.style.SUCCESS(f'   OK. Задач в БД: {task_count}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   Ошибка: {e}'))
            return
        
        # Тест 2: Создание простой задачи
        self.stdout.write('[2/4] Создание тестовой задачи...')
        try:
            task_id = async_task(
                'Asistent.management.commands.test_djangoq.test_function',
                'Hello Celery!'
            )
            self.stdout.write(self.style.SUCCESS(f'   Задача создана. ID: {task_id}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   Ошибка: {e}'))
            return
        
        # Тест 3: Проверка статуса задачи
        self.stdout.write('[3/4] Проверка статуса задачи...')
        self.stdout.write('   Ожидание выполнения (до 10 секунд)...')
        
        for i in range(10):
            time.sleep(1)
            try:
                    task = TaskResult.objects.get(task_id=task_id)
                    if task.status == 'SUCCESS':
                    self.stdout.write(self.style.SUCCESS(f'   Задача выполнена успешно за {i+1} секунд'))
                    self.stdout.write(f'   Результат: {task.result}')
                    break
                    elif task.status == 'FAILURE':
                    self.stdout.write(self.style.ERROR(f'   Задача завершилась с ошибкой'))
                    self.stdout.write(f'   Ошибка: {task.result}')
                    break
                except TaskResult.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'   Задача еще не появилась в БД (попытка {i+1}/10)'))
        else:
            self.stdout.write(self.style.WARNING('   ВНИМАНИЕ: Задача не выполнена за 10 секунд'))
            self.stdout.write('   ВАЖНО: Убедитесь что запущен celery worker')
        
        # Тест 4: Статистика
        self.stdout.write('[4/4] Общая статистика Celery...')
        total = TaskResult.objects.count()
        success = TaskResult.objects.filter(status='SUCCESS').count()
        failed = TaskResult.objects.filter(status='FAILURE').count()
        pending = TaskResult.objects.filter(status='PENDING').count()
        
        self.stdout.write(f'   Всего задач: {total}')
        self.stdout.write(f'   Успешных: {success}')
        self.stdout.write(f'   С ошибками: {failed}')
        self.stdout.write(f'   В ожидании: {pending}')
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('  ТЕСТИРОВАНИЕ ЗАВЕРШЕНО'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        
        if pending > 0:
            self.stdout.write(self.style.WARNING('ВНИМАНИЕ: Есть задачи в ожидании!'))
            self.stdout.write('  Запустите Celery worker:')
            self.stdout.write('  celery -A IdealImage_PDJ worker -l info')
            self.stdout.write('  или')
            self.stdout.write('  START_ALL_NEW.bat')


def test_function(message):
    """Тестовая функция для Celery"""
    return f"Получено сообщение: {message}"

