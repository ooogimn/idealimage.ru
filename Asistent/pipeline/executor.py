"""
Asistent/pipeline/executor.py

Адаптерный модуль, связывающий daily_article_generator с системой расписаний.
Функция execute_pipeline_by_slug запускает пайплайн по его slug-имени,
делегируя работу в Asistent.schedule и Asistent.generators.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PipelineRunLog:
    """
    Простой объект-результат выполнения пайплайна.
    Имитирует структуру run_log для обратной совместимости с daily_article_generator.
    """

    def __init__(
        self,
        *,
        status: str = "success",
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        run_id: Optional[int] = None,
    ):
        self.id = run_id
        self.status = status  # "success" | "failed" | "partial"
        self.result = result or {}
        self.error_message = error_message


# Реестр известных пайплайнов
_PIPELINE_REGISTRY: Dict[str, Any] = {}


def _load_pipeline(slug: str):
    """
    Лениво возвращает функцию-обработчик по slug пайплайна.
    Это откладывает импорт Django-моделей до момента первого вызова,
    что предотвращает проблемы с init-импортами в Celery.
    """
    if slug == "daily-horoscope-flow":
        from Asistent.schedule.horoscope import generate_horoscope_from_prompt_template
        return generate_horoscope_from_prompt_template
    return None


def execute_pipeline_by_slug(
    slug: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[PipelineRunLog]:
    """
    Запускает пайплайн генерации контента по его slug-имени.

    Args:
        slug:    Идентификатор пайплайна (например, "daily-horoscope-flow").
        payload: Словарь параметров для передачи в пайплайн.

    Returns:
        PipelineRunLog — объект с результатами запуска, либо None если пайплайн не найден.
    """
    payload = payload or {}
    logger.info("🚀 [Pipeline] Запуск пайплайна slug=%r, payload_keys=%s", slug, list(payload.keys()))

    handler = _load_pipeline(slug)

    if handler is None:
        logger.error("❌ [Pipeline] Пайплайн '%s' не зарегистрирован.", slug)
        return None

    try:
        if slug == "daily-horoscope-flow":
            result = _run_horoscope_pipeline(handler, payload)
        else:
            result = handler(payload)

        if isinstance(result, dict):
            status = "success" if result.get("success") else "failed"
            if result.get("status"):
                status = result["status"]
            context = {
                "post_id": result.get("created_posts", [None])[0].id
                if result.get("created_posts")
                else None,
                "post_status": "published" if result.get("success") else "failed",
            }
            return PipelineRunLog(
                status=status,
                result={"context": context, **result},
                error_message=result.get("error") or (
                    "; ".join(result.get("errors", [])) if result.get("errors") else None
                ),
            )

        logger.warning("⚠️ [Pipeline] Неожиданный тип результата от '%s': %s", slug, type(result))
        return PipelineRunLog(status="failed", error_message="Неожиданный тип результата")

    except Exception as exc:
        logger.exception("❌ [Pipeline] Ошибка выполнения пайплайна '%s': %s", slug, exc)
        return PipelineRunLog(status="failed", error_message=str(exc))


def _run_horoscope_pipeline(
    handler,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Запускает генерацию гороскопов.

    Если в payload есть zodiac_sign — генерирует один знак через UniversalContentGenerator.
    Если zodiac_sign не задан — генерирует все 12 знаков через schedule.horoscope.

    При этом:
    - если задан schedule_id — использует существующее расписание;
    - иначе — ищет первое активное расписание с 'horoscope' в имени или с нужной категорией.
    """
    zodiac_sign: Optional[str] = payload.get("zodiac_sign")

    # Ищем подходящее расписание
    schedule_id = payload.get("schedule_id")
    if not schedule_id:
        schedule_id = _find_horoscope_schedule_id()

    if not schedule_id:
        logger.warning(
            "⚠️ [Pipeline] Не найдено расписание для гороскопов. "
            "Создайте расписание AISchedule с 'Гороскоп' в названии в админке."
        )
        return {
            "success": False,
            "error": "no_schedule",
            "message": "Не найдено активное расписание для гороскопов. "
                       "Создайте его в '/admin/' → AI Расписания.",
        }

    if zodiac_sign:
        # Генерируем один знак
        from Asistent.generators.universal import UniversalContentGenerator, GeneratorConfig
        from Asistent.schedule.models import AISchedule

        try:
            schedule = AISchedule.objects.select_related("prompt_template", "category").get(
                id=schedule_id
            )
        except AISchedule.DoesNotExist:
            return {
                "success": False,
                "error": "schedule_not_found",
                "message": f"Расписание ID={schedule_id} не найдено",
            }

        config = GeneratorConfig.for_auto()
        config.timeout = 300

        generator = UniversalContentGenerator(
            template=schedule.prompt_template,
            config=config,
            schedule_id=schedule.id,
        )

        base_tags = payload.get("base_tags", ["гороскоп", "прогноз на завтра"])
        sign_tags = list(dict.fromkeys(base_tags + [zodiac_sign]))

        gen_payload = {
            "target_date_offset": payload.get("target_date_offset", 1),
            "publish_mode": payload.get("publish_mode", "published"),
            "title_template": payload.get("title_template"),
            "base_tags": sign_tags,
            "category": schedule.category.title if schedule.category else None,
            "zodiac_sign": zodiac_sign,
        }

        result = generator.generate(schedule_payload=gen_payload)

        if result.success and result.post_id:
            from blog.models import Post as BlogPost

            post = BlogPost.objects.get(id=result.post_id)
            return {
                "success": True,
                "status": "success",
                "created_posts": [post],
                "created_count": 1,
                "errors": [],
            }
        return {
            "success": False,
            "status": "failed",
            "created_posts": [],
            "created_count": 0,
            "errors": [result.error or "Неизвестная ошибка генерации"],
        }

    # Все 12 знаков
    return handler(schedule_id)


def _find_horoscope_schedule_id() -> Optional[int]:
    """
    Ищет первое активное расписание для гороскопов в БД.
    Критерии:
      1) is_active=True
      2) Имя содержит 'гороскоп' (регистронезависимо) или 'horoscope'
    """
    try:
        from Asistent.schedule.models import AISchedule

        qs = AISchedule.objects.filter(is_active=True).filter(
            name__icontains="гороскоп"
        )
        first = qs.first()
        if first:
            return first.id

        # Запасной вариант: любое активное расписание с 'horoscope'
        qs2 = AISchedule.objects.filter(is_active=True, name__icontains="horoscope")
        first2 = qs2.first()
        if first2:
            return first2.id

    except Exception as exc:
        logger.error("❌ [Pipeline] Ошибка поиска расписания для гороскопов: %s", exc)

    return None
