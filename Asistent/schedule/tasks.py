"""
Задачи для выполнения расписаний через Celery.
Содержит основную логику запуска расписаний и вспомогательные функции.
"""
import logging
from datetime import timedelta
from typing import Dict, Any

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from .models import AISchedule
from .strategies import (
    PromptScheduleStrategy,
    SystemScheduleStrategy,
    ManualScheduleStrategy,
    HoroscopeScheduleStrategy,
)
from .services import send_schedule_notification

logger = logging.getLogger(__name__)


# Маппинг стратегий
STRATEGY_MAP = {
    'prompt': PromptScheduleStrategy,
    'system': SystemScheduleStrategy,
    'manual': ManualScheduleStrategy,
    'horoscope': HoroscopeScheduleStrategy,
}


@shared_task(name='Asistent.schedule.tasks.run_specific_schedule', bind=True, max_retries=3)
def run_specific_schedule(self, schedule_id: int) -> Dict[str, Any]:
    """
    Основная функция для запуска AI-расписания по ID.
    Вызывается автоматически Celery Beat по расписанию.
    
    Args:
        schedule_id: ID объекта AISchedule для выполнения
    
    Returns:
        dict: Результат выполнения с ключами success, created_posts, errors
    """
    logger.info(f"🤖 [AI Schedule] Запуск расписания ID={schedule_id}")

    schedule = None

    try:
        schedule = AISchedule.objects.select_related('category', 'prompt_template').get(
            id=schedule_id
        )
        
        # Автоматическая реактивация на следующий день для расписаний автопостинга гороскопов
        now = timezone.now()
        is_horoscope = (schedule.prompt_template and 
                        schedule.prompt_template.category == 'horoscope' and
                        "Автопостинг гороскопов" in schedule.name)
        
        if not schedule.is_active and is_horoscope:
            # Проверяем: если расписание деактивировано и сейчас >= 8:00 следующего дня
            today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= today_8am:
                # Проверяем, что сегодня еще не создано гороскопов
                from blog.models import Post
                horoscope_count = Post.objects.filter(
                    created__date=now.date(),
                    tags__name__in=['гороскоп', 'прогноз на завтра']
                ).distinct().count()
                
                if horoscope_count == 0:
                    schedule.is_active = True
                    schedule.current_run_count = 0
                    schedule.update_next_run()
                    schedule.save(update_fields=['is_active', 'current_run_count', 'next_run'])
                    logger.info(f"   ✅ Расписание гороскопов автоматически активировано на новый день")
        
        if not schedule.is_active:
            logger.info(f"   ⏸️ Расписание неактивно, пропуск")
            return {
                'success': False,
                'reason': 'inactive',
                'schedule_id': schedule_id
            }

        logger.info(f"   📋 Расписание: {schedule.name}")
        logger.info(f"   📁 Категория: {schedule.category.title if schedule.category else 'Не указана'}")
        logger.info(f"   📊 Статей за запуск: {schedule.articles_per_run}")

        now = timezone.now()
        
        # ПРИОРИТИЗАЦИЯ: Гороскопы имеют высокий приоритет
        is_horoscope_schedule = _check_if_horoscope_schedule(schedule)
        
        if is_horoscope_schedule:
            # Гороскопы имеют приоритет - блокируем другие задачи
            _set_horoscope_priority(now)
            logger.info(f"   ⚡ Гороскопы имеют приоритет, другие задачи приостановлены")
        else:
            # Если это НЕ расписание гороскопов - проверяем блокировку
            if _is_horoscope_priority_active():
                logger.info(f"   ⏸️ Пропуск: активна генерация гороскопов (приоритет)")
                return {
                    'success': False,
                    'status': 'skipped',
                    'reason': 'horoscope_priority',
                    'message': 'Другие задачи заблокированы во время генерации гороскопов'
                }
        
        # Проверка частоты запусков
        if schedule.last_run:
            time_since_last = (now - schedule.last_run).total_seconds()
            min_interval = 270  # 5 минут минимум между запусками

            if time_since_last < min_interval:
                logger.warning(
                    f"   ⏸️ Слишком частый запуск! "
                    f"Прошло {int(time_since_last/60)} минут, нужно минимум {min_interval/60}"
                )
                return {
                    'success': False,
                    'reason': 'too_soon',
                    'wait_seconds': int(min_interval - time_since_last)
                }

        # Проверяем, нужно ли использовать специальную функцию для гороскопов
        if is_horoscope_schedule:
            logger.info("   🔮 Режим: генерация гороскопа из шаблона промпта")
            # Импортируем из модуля horoscope
            from .horoscope import generate_horoscope_from_prompt_template
            return generate_horoscope_from_prompt_template(schedule_id)

        # Выбор стратегии выполнения
        strategy_key = schedule.strategy_type or 'prompt'
        if strategy_key not in STRATEGY_MAP:
            strategy_key = 'prompt' if schedule.prompt_template else 'system'

        strategy_class = STRATEGY_MAP.get(strategy_key, PromptScheduleStrategy)
        logger.info(f"   ⚙️ Стратегия запуска: {strategy_key}")

        strategy = strategy_class(schedule)
        return strategy.execute()

    except AISchedule.DoesNotExist:
        logger.error(f"   ❌ AISchedule ID={schedule_id} не найдено или неактивно")
        _handle_schedule_not_found(schedule_id)
        return {'success': False, 'error': 'schedule_not_found', 'schedule_id': schedule_id}

    except Exception as e:
        logger.exception(f"   ❌ Критическая ошибка при выполнении расписания ID={schedule_id}: {e}")

        if schedule:
            send_schedule_notification(schedule, None, success=False, error=str(e))

        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'schedule_id': schedule_id
        }


# ============================================================================
# Вспомогательные функции
# ============================================================================

def _check_if_horoscope_schedule(schedule: AISchedule) -> bool:
    """Проверяет, является ли расписание гороскопом"""
    if schedule.prompt_template:
        if (schedule.prompt_template.category == 'horoscope' or 
            schedule.prompt_template.name == 'DAILY_HOROSCOPE_PROMPT'):
            return True
    elif schedule.payload_template.get('prompt_name') == 'DAILY_HOROSCOPE_PROMPT':
        return True
    return False


def _set_horoscope_priority(now):
    """Устанавливает приоритет для гороскопов"""
    today_str = now.date().isoformat()
    blocking_key = f"horoscope_generation_active:{today_str}"
    horoscope_priority_key = "horoscope_generation_priority"
    
    cache.set(horoscope_priority_key, True, timeout=300)  # 5 минут приоритета
    cache.set(blocking_key, True, timeout=1800)  # 30 минут блокировки других задач


def _is_horoscope_priority_active() -> bool:
    """Проверяет, активен ли приоритет гороскопов"""
    now = timezone.now()
    today_str = now.date().isoformat()
    blocking_key = f"horoscope_generation_active:{today_str}"
    horoscope_priority_key = "horoscope_generation_priority"
    
    return bool(cache.get(blocking_key) or cache.get(horoscope_priority_key))


def _handle_schedule_not_found(schedule_id: int):
    """Обрабатывает ситуацию, когда расписание не найдено"""
    try:
        from django.contrib.auth.models import User
        from Asistent.models import AIConversation, AIMessage
        
        admin = User.objects.filter(is_superuser=True).first()
        if admin:
            conversation, _ = AIConversation.objects.get_or_create(
                admin=admin,
                title='🔴 Мониторинг в реальном времени',
                defaults={'is_active': True}
            )
            
            message = f"⚠️ ПРОБЛЕМА С РАСПИСАНИЕМ!\n\n"
            message += f"Расписание ID={schedule_id} не найдено в базе данных.\n"
            message += f"Django-Q пытается запустить несуществующее расписание.\n\n"
            message += f"💡 РЕШЕНИЕ:\n"
            message += f"  1. Проверьте таблицу AISchedule - возможно расписание было удалено\n"
            message += f"  2. Удалите старую задачу Django-Q\n"
            message += f"  3. Запустите синхронизацию: python manage.py sync_schedules --force\n"
            
            AIMessage.objects.create(
                conversation=conversation,
                role='assistant',
                content=message
            )
    except Exception as notify_error:
        logger.error(f"   ⚠️ Не удалось отправить уведомление: {notify_error}")

    # Удаляем задачу Celery PeriodicTask для несуществующего расписания
    try:
        from django_celery_beat.models import PeriodicTask
        task_name = f'ai_schedule_{schedule_id}'
        PeriodicTask.objects.filter(name=task_name).delete()
        logger.info("   🗑️ Удалена задача Celery для несуществующего расписания")
    except Exception as e:
        logger.error(f"   ⚠️ Не удалось удалить задачу Celery: {e}")


def calculate_next_run_delta(frequency: str) -> timedelta:
    """
    Вычисляет интервал до следующего запуска на основе частоты.
    
    Args:
        frequency: Частота выполнения (daily, weekly, hourly и т.д.)
    
    Returns:
        timedelta: Интервал до следующего запуска
    """
    frequency_map = {
        'hourly': timedelta(hours=1),
        'every_2_hours': timedelta(hours=2),
        'every_3_hours': timedelta(hours=3),
        'every_4_hours': timedelta(hours=4),
        'every_6_hours': timedelta(hours=6),
        'every_8_hours': timedelta(hours=8),
        'every_12_hours': timedelta(hours=12),
        'daily': timedelta(days=1),
        'twice_daily': timedelta(hours=12),
        'weekly': timedelta(weeks=1),
        'biweekly': timedelta(weeks=2),
        'monthly': timedelta(days=30),
    }
    
    return frequency_map.get(frequency, timedelta(days=1))


# ============================================================================
# Функции для обратной совместимости
# ============================================================================

def run_prompt_schedule(schedule, now):
    """
    Совместимость: проксирует выполнение в новую инфраструктуру.
    Используется в старом коде Asistent.tasks
    """
    from .context import ScheduleContext
    from .services import PromptGenerationWorkflow
    
    context = ScheduleContext(schedule, run=None)
    current_time = now if isinstance(now, type(timezone.now())) else timezone.now()
    workflow = PromptGenerationWorkflow(schedule=schedule, context=context)
    return workflow.run(current_time=current_time)


def run_system_task(schedule, now, task_name):
    """
    Совместимость: проксирует выполнение в новую инфраструктуру.
    Используется в старом коде Asistent.tasks
    """
    from .context import ScheduleContext
    from .services import SystemTaskRunner
    
    runner = SystemTaskRunner(schedule=schedule, context=ScheduleContext(schedule, run=None))
    context_now = now if isinstance(now, type(timezone.now())) else timezone.now()
    return runner.run(current_time=context_now)


@shared_task(name='Asistent.schedule.tasks.generate_all_horoscopes', bind=True, max_retries=2)
def generate_all_horoscopes(self) -> Dict[str, Any]:
    """
    Генерирует все 12 гороскопов последовательно.
    Запускается по расписанию каждый день в 10:00.
    
    Использует существующую инфраструктуру:
    - run_specific_schedule() для каждого расписания
    - Приоритизация гороскопов
    - Уведомления через send_schedule_notification
    
    Returns:
        dict: Результат выполнения с ключами:
            - success: bool - общий успех (все гороскопы созданы)
            - created_posts: List[int] - ID созданных постов
            - errors: List[Dict] - список ошибок
            - total: int - общее количество расписаний
    """
    import time
    
    logger.info("🔮 [Гороскопы] Запуск генерации всех 12 гороскопов")
    
    # Получаем все активные расписания гороскопов
    schedules = AISchedule.objects.filter(
        prompt_template__category='horoscope',
        is_active=True
    ).order_by('id')
    
    if not schedules.exists():
        logger.error("❌ Активные расписания гороскопов не найдены")
        return {
            'success': False,
            'error': 'no_active_schedules',
            'created_posts': [],
            'errors': [],
            'total': 0
        }
    
    created_posts = []
    errors = []
    
    logger.info(f"📋 Найдено расписаний: {schedules.count()}")
    
    # Устанавливаем приоритет гороскопов
    now = timezone.now()
    _set_horoscope_priority(now)
    logger.info("   ⚡ Установлен приоритет гороскопов")
    
    try:
        for schedule in schedules:
            logger.info(f"   📅 Генерация: {schedule.name} (ID: {schedule.id})")
            
            try:
                # Используем существующую функцию run_specific_schedule
                result = run_specific_schedule(schedule.id)
                
                if result.get('success'):
                    # Используем список всех созданных постов, если он есть
                    result_posts = result.get('created_posts', [])
                    if result_posts:
                        # Добавляем все посты из списка
                        created_posts.extend(result_posts)
                        logger.info(f"   ✅ Успешно: создано {len(result_posts)} постов (ID: {', '.join(map(str, result_posts))})")
                    else:
                        # Обратная совместимость: если есть только post_id
                        post_id = result.get('post_id')
                        if post_id:
                            created_posts.append(post_id)
                            logger.info(f"   ✅ Успешно: Post ID={post_id}")
                else:
                    error_msg = result.get('error') or result.get('reason', 'unknown_error')
                    errors.append({
                        'schedule_id': schedule.id,
                        'schedule_name': schedule.name,
                        'error': error_msg
                    })
                    logger.error(f"   ❌ Ошибка: {error_msg}")
            
            except Exception as e:
                error_msg = str(e)
                errors.append({
                    'schedule_id': schedule.id,
                    'schedule_name': schedule.name,
                    'error': error_msg
                })
                logger.error(f"   ❌ Исключение: {error_msg}", exc_info=True)
            
            # Задержка между запусками (чтобы не перегрузить API)
            if schedule != schedules.last():
                time.sleep(3)
    
    finally:
        # Снимаем приоритет после завершения
        # (блокировка автоматически истечёт через timeout в кэше)
        logger.debug("   🔓 Приоритет гороскопов будет снят автоматически")
    
    success = len(errors) == 0
    
    logger.info(
        f"✅ Генерация всех гороскопов завершена: "
        f"успешно={len(created_posts)}, ошибок={len(errors)}"
    )
    
    return {
        'success': success,
        'created_posts': created_posts,
        'errors': errors,
        'total': schedules.count()
    }
