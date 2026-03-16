"""
Команда для тестирования AI-агента и Celery
Проверяет все компоненты системы агента
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from Asistent.tasks import async_task
from django_celery_results.models import TaskResult
import time

User = get_user_model()


class Command(BaseCommand):
    help = 'Тестирование AI-агента и его интеграции с Celery'

    def add_arguments(self, parser):
        parser.add_argument(
            '--full',
            action='store_true',
            help='Полное тестирование включая реальные API запросы'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  🤖 ДИАГНОСТИКА AI-АГЕНТА'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')

        full_test = options.get('full', False)

        # ======================================================================
        # ЭТАП 1: ПРОВЕРКА DJANGO-Q
        # ======================================================================
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write(self.style.HTTP_INFO('ЭТАП 1: Проверка Celery'))
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write('')

        # 1.1 Проверка подключения к БД
        self.stdout.write('[1.1] Проверка таблиц Celery Results...')
        try:
            total_tasks = TaskResult.objects.count()
            pending_tasks = TaskResult.objects.filter(status='PENDING').count()
            success_tasks = TaskResult.objects.filter(status='SUCCESS').count()
            failed_tasks = TaskResult.objects.filter(status='FAILURE').count()

            self.stdout.write(self.style.SUCCESS(f'   ✓ БД доступна'))
            self.stdout.write(f'   • Всего задач: {total_tasks}')
            self.stdout.write(f'   • В ожидании: {pending_tasks}')
            self.stdout.write(f'   • Успешных: {success_tasks}')
            self.stdout.write(f'   • С ошибками: {failed_tasks}')

            if pending_tasks > 0:
                self.stdout.write(self.style.WARNING(f'\n   ⚠️ ВНИМАНИЕ: {pending_tasks} задач ожидают выполнения!'))
                self.stdout.write(self.style.WARNING('   Убедитесь что celery worker запущен'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))
            return

        self.stdout.write('')

        # 1.2 Проверка celery worker
        self.stdout.write('[1.2] Проверка работы celery worker...')
        try:
            # Создаем простую тестовую задачу
            task_id = async_task(
                'Asistent.management.commands.test_ai_agent.simple_test_task',
                'test_message',
                task_name='test_simple_task'
            )
            self.stdout.write(f'   Создана тестовая задача: {task_id}')
            self.stdout.write('   Ожидание выполнения (5 секунд)...')

            # Ждем выполнения
            qcluster_working = False
            for i in range(5):
                time.sleep(1)
                try:
                    task = TaskResult.objects.get(task_id=task_id)
                    if task.status == 'SUCCESS':
                        self.stdout.write(self.style.SUCCESS(f'   ✓ Celery worker РАБОТАЕТ! Задача выполнена за {i+1} сек'))
                        qcluster_working = True
                        break
                    elif task.status == 'FAILURE':
                        self.stdout.write(self.style.ERROR('   ✗ Задача завершилась с ошибкой'))
                        self.stdout.write(f'   Ошибка: {task.result}')
                        break
                except TaskResult.DoesNotExist:
                    pass

            if not qcluster_working:
                self.stdout.write(self.style.ERROR('   ✗ Celery worker НЕ РАБОТАЕТ или медленно!'))
                self.stdout.write('')
                self.stdout.write(self.style.WARNING('   РЕШЕНИЕ:'))
                self.stdout.write('   1. Запустите в отдельном окне: celery -A IdealImage_PDJ worker -l info')
                self.stdout.write('   2. Или используйте: START_ALL_NEW.bat -> выбор [2]')
                self.stdout.write('')
                self.stdout.write(self.style.ERROR('   ДАЛЬНЕЙШЕЕ ТЕСТИРОВАНИЕ НЕВОЗМОЖНО БЕЗ CELERY WORKER'))
                return

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))
            return

        self.stdout.write('')

        # ======================================================================
        # ЭТАП 2: ПРОВЕРКА КОМПОНЕНТОВ AI-АГЕНТА
        # ======================================================================
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write(self.style.HTTP_INFO('ЭТАП 2: Проверка компонентов AI-агента'))
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write('')

        # 2.1 Проверка моделей
        self.stdout.write('[2.1] Проверка моделей...')
        try:
            from Asistent.models import (
                AIConversation, AIMessage, AITask, 
                AIKnowledgeBase, AISchedule
            )

            conversations_count = AIConversation.objects.count()
            messages_count = AIMessage.objects.count()
            tasks_count = AITask.objects.count()
            knowledge_count = AIKnowledgeBase.objects.count()
            schedules_count = AISchedule.objects.count()

            self.stdout.write(self.style.SUCCESS('   ✓ Все модели доступны'))
            self.stdout.write(f'   • Диалогов: {conversations_count}')
            self.stdout.write(f'   • Сообщений: {messages_count}')
            self.stdout.write(f'   • AI-задач: {tasks_count}')
            self.stdout.write(f'   • Записей в базе знаний: {knowledge_count}')
            self.stdout.write(f'   • Расписаний: {schedules_count}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))

        self.stdout.write('')

        # 2.2 Проверка GigaChat API
        self.stdout.write('[2.2] Проверка GigaChat API...')
        try:
            from Asistent.gigachat_api import get_gigachat_client
            from django.conf import settings

            api_key = settings.GIGACHAT_API_KEY

            if not api_key:
                self.stdout.write(self.style.WARNING('   ⚠️ GIGACHAT_API_KEY не установлен'))
                self.stdout.write('   Установите ключ в .env файле')
            else:
                self.stdout.write(self.style.SUCCESS('   ✓ API ключ установлен'))

                if full_test:
                    self.stdout.write('   Проверка подключения к GigaChat...')
                    client = get_gigachat_client()
                    if client.check_connection():
                        self.stdout.write(self.style.SUCCESS('   ✓ GigaChat API РАБОТАЕТ!'))
                    else:
                        self.stdout.write(self.style.ERROR('   ✗ GigaChat API не отвечает'))
                else:
                    self.stdout.write('   (используйте --full для проверки подключения)')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))

        self.stdout.write('')

        # 2.3 Проверка парсера команд
        self.stdout.write('[2.3] Проверка парсера команд...')
        try:
            from Asistent.ai_agent import CommandParser

            test_commands = [
                ('генерируй статью про моду', 'generate_article'),
                ('спарси видео https://youtube.com/watch?v=123', 'parse_video'),
                ('распредели бонусы', 'distribute_bonuses'),
                ('создай расписание на неделю', 'create_schedule'),
            ]

            parsed_count = 0
            for command, expected_type in test_commands:
                task_type, params = CommandParser.parse(command)
                if task_type == expected_type:
                    parsed_count += 1

            self.stdout.write(self.style.SUCCESS(f'   ✓ Парсер работает: {parsed_count}/{len(test_commands)} команд распознано'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))

        self.stdout.write('')

        # ======================================================================
        # ЭТАП 3: ТЕСТИРОВАНИЕ ОБРАБОТЧИКОВ ЗАДАЧ
        # ======================================================================
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write(self.style.HTTP_INFO('ЭТАП 3: Тестирование обработчиков AI-задач'))
        self.stdout.write(self.style.HTTP_INFO('=' * 70))
        self.stdout.write('')

        # 3.1 Создание тестового пользователя
        self.stdout.write('[3.1] Подготовка тестовых данных...')
        try:
            admin_user = User.objects.filter(is_superuser=True).first()
            if not admin_user:
                self.stdout.write(self.style.WARNING('   ⚠️ Нет суперпользователя. Создаю тестового...'))
                admin_user = User.objects.create_superuser(
                    username='test_admin',
                    email='test@test.com',
                    password='test123'
                )
            
            self.stdout.write(self.style.SUCCESS(f'   ✓ Пользователь: {admin_user.username}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))
            return

        self.stdout.write('')

        # 3.2 Тест команды через AI-агента
        self.stdout.write('[3.2] Тест команды "распредели бонусы"...')
        try:
            from Asistent.models import AIConversation
            from Asistent.ai_agent import AIAgent

            # Создаем диалог
            conversation, _ = AIConversation.objects.get_or_create(
                admin=admin_user,
                title='Тестовый диалог',
                defaults={'is_active': True}
            )

            # Отправляем команду
            agent = AIAgent()
            result = agent.process_message(
                admin_user,
                'распредели бонусы',
                conversation
            )

            if result.get('task_created'):
                task_id = result.get('task_id')
                self.stdout.write(self.style.SUCCESS(f'   ✓ Задача создана: ID={task_id}'))
                self.stdout.write(f'   Ответ агента: {result.get("response")[:100]}...')

                # Проверяем выполнение
                self.stdout.write('   Ожидание выполнения задачи (10 секунд)...')
                
                from Asistent.models import AITask
                task_executed = False
                for i in range(10):
                    time.sleep(1)
                    task = AITask.objects.get(id=task_id)
                    if task.status == 'completed':
                        self.stdout.write(self.style.SUCCESS(f'   ✓ Задача выполнена за {i+1} сек!'))
                        self.stdout.write(f'   Результат: {str(task.result)[:100]}...')
                        task_executed = True
                        break
                    elif task.status == 'failed':
                        self.stdout.write(self.style.ERROR('   ✗ Задача завершилась с ошибкой'))
                        self.stdout.write(f'   Ошибка: {task.error_message}')
                        break

                if not task_executed and task.status == 'pending':
                    self.stdout.write(self.style.WARNING('   ⚠️ Задача еще не выполнена'))
                    self.stdout.write(f'   Статус: {task.status}')
            else:
                self.stdout.write(self.style.WARNING('   ⚠️ Команда не распознана как задача'))
                self.stdout.write(f'   Ответ: {result.get("response")}')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   ✗ Ошибка: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())

        self.stdout.write('')

        # ======================================================================
        # ИТОГОВАЯ ИНФОРМАЦИЯ
        # ======================================================================
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  ✅ ДИАГНОСТИКА ЗАВЕРШЕНА'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')

        if qcluster_working:
            self.stdout.write(self.style.SUCCESS('✓ Celery worker работает корректно'))
            self.stdout.write(self.style.SUCCESS('✓ AI-агент готов к работе'))
            self.stdout.write('')
            self.stdout.write('📍 Интерфейс AI-чата: http://127.0.0.1:8000/asistent/chat/')
            self.stdout.write('📍 Админка задач: http://127.0.0.1:8000/admin/django_celery_results/taskresult/')
        else:
            self.stdout.write(self.style.ERROR('✗ Есть проблемы с Celery worker'))
            self.stdout.write('')
            self.stdout.write('РЕШЕНИЕ:')
            self.stdout.write('1. Запустите celery worker: celery -A IdealImage_PDJ worker -l info')
            self.stdout.write('2. Или используйте START_ALL_NEW.bat')

        self.stdout.write('')


def simple_test_task(message):
    """Простая тестовая функция"""
    return f"OK: {message}"

