"""
Генерация гороскопов через промпт-шаблон
Упрощенная версия - использует UniversalContentGenerator
"""
import json
import logging
from typing import Dict, Any
from django.utils import timezone
from django.core.cache import cache

from Asistent.generators.universal import UniversalContentGenerator, GeneratorConfig, GeneratorMode
from Asistent.schedule.models import AISchedule
from Asistent.constants import ZODIAC_SIGNS
from blog.models import Post

logger = logging.getLogger(__name__)


def generate_horoscope_from_prompt_template(schedule_id: int) -> Dict[str, Any]:
    """
    Генерация всех 12 гороскопов для расписания.
    
    Args:
        schedule_id: ID расписания AISchedule
    
    Returns:
        dict: Результат генерации с ключами success, created_posts, errors
    """
    logger.info(f"🔮 [Гороскоп] Запуск генерации для расписания ID={schedule_id}")
    
    try:
        schedule = AISchedule.objects.select_related('prompt_template', 'category').get(id=schedule_id)
        
        if not schedule.prompt_template:
            return {
                'success': False,
                'error': 'no_prompt_template',
                'message': 'У расписания нет шаблона промпта'
            }
        
        logger.info(f"   📋 Расписание: {schedule.name}")
        logger.info(f"   📊 Статей за запуск: {schedule.articles_per_run}")
        logger.info(f"   🔮 Режим: генерация гороскопа из шаблона промпта")
        
        # Получаем параметры из payload_template (может быть dict или JSON-строка из БД)
        raw_payload = schedule.payload_template
        if isinstance(raw_payload, str):
            try:
                payload = json.loads(raw_payload) if raw_payload.strip() else {}
            except (json.JSONDecodeError, AttributeError):
                payload = {}
        elif isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            payload = {}
        generation_delay = payload.get('generation_delay', 20)
        retry_count = payload.get('retry_count', 2)
        retry_delay = payload.get('retry_delay', 60)
        skip_signs = payload.get('skip_signs', [])
        check_cooldown = payload.get('check_cooldown', True)
        daily_limit = int(payload.get('daily_limit', 12) or 12)
        
        logger.info(
            "   ⚙️ Параметры: задержка=%sс, retry=%s раз, retry_delay=%sс, "
            "проверка cooldown=%s, daily_limit=%s",
            generation_delay,
            retry_count,
            retry_delay,
            check_cooldown,
            daily_limit,
        )
        
        if skip_signs:
            logger.info(f"   ⏭️ Пропуск знаков: {', '.join(skip_signs)}")
        
        # Фильтруем знаки и уважаем articles_per_run (экономия токенов)
        all_signs = [s for s in ZODIAC_SIGNS if s not in skip_signs]
        total_signs = len(all_signs)
        if total_signs == 0:
            return {
                'success': False,
                'created_posts': [],
                'created_count': 0,
                'errors': ['Нет знаков для генерации после применения skip_signs'],
                'status': 'failed',
            }

        per_run = max(1, int(schedule.articles_per_run or 1))
        per_run = min(per_run, total_signs)

        # Курсор ротации: каждый запуск берет следующий знак(и), а не все 12.
        cursor_key = f"horoscope_schedule_cursor:{schedule.id}"
        start_idx = cache.get(cursor_key, 0)
        if not isinstance(start_idx, int) or start_idx < 0:
            start_idx = 0
        start_idx = start_idx % total_signs

        signs_to_generate = [
            all_signs[(start_idx + i) % total_signs]
            for i in range(per_run)
        ]

        next_idx = (start_idx + per_run) % total_signs
        cache.set(cursor_key, next_idx, timeout=60 * 60 * 24 * 30)

        logger.info(
            "   📋 Ротация гороскопов: за запуск %s из %s "
            "(start_idx=%s -> next_idx=%s)",
            per_run,
            total_signs,
            start_idx,
            next_idx,
        )
        
        # ПРЕДЗАГРУЗКА ЭФЕМЕРИД: загружаем один раз перед генерацией всех гороскопов
        # Это предотвращает множественные запросы к JPL Horizons API
        logger.info("   🔭 Предзагрузка эфемерид для всех гороскопов...")
        from Asistent.services.astro_context import AstrologyContextBuilder
        ephemeris_preloaded = AstrologyContextBuilder.preload_ephemeris()
        if ephemeris_preloaded:
            logger.info("   ✅ Эфемериды предзагружены и закэшированы")
        else:
            logger.warning("   ⚠️ Не удалось предзагрузить эфемериды, будет использоваться кэш или запросы по требованию")
        
        created_posts = []
        errors = []

        # Дневной лимит защищает от повторной генерации при частом cron.
        today_generated = Post.objects.filter(
            created__date=timezone.now().date(),
            tags__name='гороскоп',
        ).distinct().count()
        if today_generated >= daily_limit:
            logger.info(
                "   ⏸️ Достигнут дневной лимит: %s/%s. Генерация пропущена до следующего дня.",
                today_generated,
                daily_limit,
            )
            return {
                'success': True,
                'created_posts': [],
                'created_count': 0,
                'errors': [],
                'status': 'success',
                'skipped': True,
                'reason': 'daily_limit_reached',
                'daily_limit': daily_limit,
                'generated_today': today_generated,
            }
        
        # Генерируем каждый гороскоп
        total_current_run = len(signs_to_generate)
        for idx, zodiac_sign in enumerate(signs_to_generate, 1):
            logger.info(f"   [{idx}/{total_current_run}] Генерация гороскопа для {zodiac_sign}...")
            
            try:
                # Создаем конфигурацию генератора
                config = GeneratorConfig.for_auto()
                config.timeout = 300
                config.retry_count = retry_count
                
                # Создаем генератор
                generator = UniversalContentGenerator(
                    template=schedule.prompt_template,
                    config=config,
                    schedule_id=schedule.id
                )
                
                # Параметры для генерации
                schedule_payload = {
                    'target_date_offset': payload.get('target_date_offset', 1),
                    'title_template': payload.get('title_template'),
                    'base_tags': payload.get('base_tags', ['гороскоп', 'прогноз на завтра']),
                    'category': schedule.category.title if schedule.category else None,
                    'zodiac_sign': zodiac_sign,
                    # Для гороскопов FAQ по умолчанию отключен (экономия токенов).
                    # Можно явно включить через payload: {"disable_faq": false}
                    'disable_faq': payload.get('disable_faq', True),
                }
                
                # Генерируем
                result = generator.generate(schedule_payload=schedule_payload)
                
                if result.success and result.post_id:
                    from blog.models import Post
                    post = Post.objects.get(id=result.post_id)
                    created_posts.append(post)
                    logger.info(f"   ✅ Гороскоп для {zodiac_sign} создан: {post.title}")
                else:
                    error_msg = result.error or 'Неизвестная ошибка'
                    errors.append(f"{zodiac_sign}: {error_msg}")
                    logger.error(f"   ❌ Ошибка генерации для {zodiac_sign}: {error_msg}")
                
                # Задержка между гороскопами (кроме последнего)
                if idx < total_current_run:
                    import time
                    time.sleep(generation_delay)
            
            except Exception as e:
                error_msg = f"Ошибка генерации для {zodiac_sign}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"   ❌ {error_msg}", exc_info=True)
        
        # Результат
        success = len(created_posts) > 0 and len(errors) == 0
        
        logger.info(f"   ✅ Генерация завершена: создано {len(created_posts)}/{total_signs}, ошибок: {len(errors)}")
        
        return {
            'success': success,
            'created_posts': created_posts,
            'created_count': len(created_posts),
            'errors': errors,
            'status': 'success' if success else 'partial' if created_posts else 'failed'
        }
    
    except AISchedule.DoesNotExist:
        logger.error(f"❌ Расписание ID={schedule_id} не найдено")
        return {
            'success': False,
            'error': 'schedule_not_found',
            'message': f'Расписание ID={schedule_id} не найдено'
        }
    except Exception as e:
        logger.error(f"❌ Критическая ошибка генерации гороскопов: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'message': f'Критическая ошибка: {str(e)}'
        }

