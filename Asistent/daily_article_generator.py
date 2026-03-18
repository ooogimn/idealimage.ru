# Asistent/daily_article_generator.py
from __future__ import annotations

from typing import List, Optional

from django.conf import settings
from blog.models import Post
import requests
import logging

from Asistent.pipeline.executor import execute_pipeline_by_slug
from Asistent.services.yandex_webmaster import get_yandex_webmaster_client

logger = logging.getLogger(__name__)


# ========================================================================
# Наследие: психологические статьи (совместимость со старыми расписаниями)
# ========================================================================
def generate_daily_psychology_article(*_args, **_kwargs) -> dict:
    """
    Совместимая заглушка для устаревших задач Django-Q.

    Ранее психологические дайджесты генерировались отдельным скриптом.
    После перехода на систему расписаний AI эта функция оставлена,
    чтобы старые записи в БД не падали — теперь это no-op.
    """
    logger.info(
        "🧠 generate_daily_psychology_article: обработан вызов устаревшего расписания (выполняется no-op)."
    )
    return {
        "success": True,
        "status": "noop",
        "message": "Legacy psychology generator перенаправлен на новый pipeline.",
    }


# ========================================================================
# Асинхронная индексация статьи
# ========================================================================
def submit_post_for_indexing(post_id: int):
    """Асинхронная индексация статьи."""
    try:
        post = Post.objects.get(id=post_id, status='published')
        post_url = f"{settings.SITE_URL.rstrip('/')}{post.get_absolute_url()}"

        # Используем тот же код, что и раньше, но асинхронно
        results = {k: False for k in ['yandex', 'google', 'bing', 'yahoo', 'indexnow']}

        # Яндекс
        try:
            client = get_yandex_webmaster_client()
            yandex_result = client.enqueue_recrawl(post_url)
            results['yandex'] = bool(yandex_result.get('success'))
            if not results['yandex']:
                logger.error(f"Яндекс индексация: {yandex_result.get('error')}")
        except Exception as e:
            logger.error(f"Яндекс индексация: {e}")

        # Google
        try:
            sitemap_url = f"{settings.SITE_URL}/sitemap.xml"
            ping_url = f"https://www.google.com/ping?sitemap={sitemap_url}"
            resp = requests.get(ping_url, timeout=10)
            results['google'] = resp.status_code == 200
        except Exception as e:
            logger.error(f"Google: {e}")

        # Bing / IndexNow
        for key_name, api_url, result_key in [
            ('BING_INDEXNOW_KEY', 'https://www.bing.com/indexnow', 'bing'),
            ('INDEXNOW_KEY', 'https://api.indexnow.org/indexnow', 'indexnow')
        ]:
            try:
                if hasattr(settings, key_name):
                    key = getattr(settings, key_name)
                    payload = {
                        "host": settings.SITE_URL.replace('https://', '').replace('http://', ''),
                        "key": key,
                        "urlList": [post_url]
                    }
                    if key_name == 'INDEXNOW_KEY':
                        payload["keyLocation"] = f"{settings.SITE_URL}/{key}.txt"
                    resp = requests.post(api_url, json=payload, timeout=10)
                    results[result_key] = resp.status_code == 200
            except Exception as e:
                logger.error(f"{result_key}: {e}")

        results['yahoo'] = results['bing'] or results['indexnow']
        logger.info(f"Индексация {post_url}: {results}")

    except Post.DoesNotExist:
        logger.error(f"Post {post_id} не найден")
    except Exception as e:
        logger.error(f"Ошибка индексации: {e}", exc_info=True)


from Asistent.constants import ZODIAC_SIGNS as HOROSCOPE_SIGNS


def _run_horoscope_batch(
    *,
    slug: str,
    target_date_offset: int,
    publish_mode: str,
    title_template: str,
    description_template: str,
    base_tags: List[str],
    prompt_name: Optional[str] = None,
    image_prompt_name: Optional[str] = None,
) -> dict:
    """
    Запускает пайплайн гороскопов для всех знаков зодиака.
    """
    summary = {
        "success": True,
        "total": len(HOROSCOPE_SIGNS),
        "processed": 0,
        "completed": 0,
        "runs": [],
    }

    for sign in HOROSCOPE_SIGNS:
        payload = {
            "zodiac_sign": sign,
            "target_date_offset": target_date_offset,
            "publish_mode": publish_mode,
            "title_template": title_template,
            "description_template": description_template,
            "base_tags": list(dict.fromkeys(base_tags + [sign])),
        }
        if prompt_name:
            payload["prompt_name"] = prompt_name
        if image_prompt_name:
            payload["image_prompt_name"] = image_prompt_name

        run_log = execute_pipeline_by_slug(slug, payload)
        summary["processed"] += 1

        if not run_log:
            summary["success"] = False
            summary["runs"].append(
                {"zodiac_sign": sign, "status": "missing_pipeline", "run_id": None}
            )
            continue

        run_details = {
            "zodiac_sign": sign,
            "status": run_log.status,
            "run_id": run_log.id,
        }

        context = (run_log.result or {}).get("context") if run_log.result else None
        if context:
            run_details["post_id"] = context.get("post_id")
            run_details["post_status"] = context.get("post_status")

        summary["runs"].append(run_details)

        if run_log.status == "success":
            summary["completed"] += 1
        else:
            summary["success"] = False

    return summary


def generate_single_horoscope(zodiac_sign: Optional[str] = None) -> dict:
    """
    Генерация одного гороскопа через пайплайн `daily-horoscope-flow`.
    Используется расписанием для публикации по одному знаку за раз.
    
    Args:
        zodiac_sign: Знак зодиака (опционально). Если не указан, используется ротация.
    
    Returns:
        dict: Результат выполнения пайплайна
    """
    from Asistent.pipeline.executor import execute_pipeline_by_slug
    from django.utils import timezone
    from blog.models import Post

    # ПРЕДОХРАНИТЕЛЬ: Проверка на дубликат за сегодня
    if zodiac_sign:
        today = timezone.now().date()
        if Post.objects.filter(
            title__icontains=zodiac_sign,
            category__slug='intellektualnye-prognozy',
            created__date=today,
            status='published'
        ).exists():
            logger.warning(f"🛑 Дубликат {zodiac_sign} обнаружен. Пропуск генерации.")
            return {"success": False, "status": "already_exists"}
    
    payload = {
        "target_date_offset": 1,
        "publish_mode": "published",
        "title_template": "{zodiac_sign} — гороскоп на {horoscope_target_date_display}",
        "description_template": "Ежедневный гороскоп для {zodiac_sign} на {horoscope_target_date_display}.",
        "base_tags": ["гороскоп", "прогноз на завтра"],
        "prompt_name": "DAILY_HOROSCOPE_PROMPT",
        "image_prompt_name": "DAILY_HOROSCOPE_PROMPT",
    }
    
    if zodiac_sign:
        payload["zodiac_sign"] = zodiac_sign
    
    run_log = execute_pipeline_by_slug("daily-horoscope-flow", payload)
    
    if not run_log:
        return {
            "success": False,
            "error": "pipeline_not_found",
            "message": "Пайплайн daily-horoscope-flow не найден или отключён"
        }
    
    return {
        "success": run_log.status == "success",
        "status": run_log.status,
        "run_id": run_log.id,
        "result": run_log.result or {},
        "error": run_log.error_message,
    }


def generate_daily_horoscopes():
    """
    Генерация ежедневных гороскопов через пайплайн `daily-horoscope-flow`.
    """
    return _run_horoscope_batch(
        slug="daily-horoscope-flow",
        target_date_offset=1,
        publish_mode="published",
        title_template="{zodiac_sign} — гороскоп на {horoscope_target_date_display}",
        description_template="Ежедневный гороскоп для {zodiac_sign} на {horoscope_target_date_display}.",
        base_tags=["гороскоп", "прогноз на завтра"],
        prompt_name="DAILY_HOROSCOPE_PROMPT",
        image_prompt_name="DAILY_HOROSCOPE_PROMPT",
    )


def generate_weekly_horoscopes():
    """
    Генерация недельных гороскопов (использует тот же пайплайн, но с другим шаблоном).
    """
    return _run_horoscope_batch(
        slug="daily-horoscope-flow",
        target_date_offset=7,
        publish_mode="draft",
        title_template="{zodiac_sign} — недельный гороскоп",
        description_template="Недельный гороскоп для {zodiac_sign}.",
        base_tags=["гороскоп", "недельный прогноз"],
        prompt_name="WEEKLY_HOROSCOPE_PROMPT",
        image_prompt_name="DAILY_HOROSCOPE_PROMPT",
    )
