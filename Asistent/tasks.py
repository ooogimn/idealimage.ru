"""
Асинхронные задачи для AI-ассистента
Используется Celery + Redis
"""
import json
import logging
from datetime import timedelta, datetime
from typing import Any, Callable, Dict, Optional

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from Asistent.schedule.context import ScheduleContext
from Asistent.schedule.services import (
    PromptGenerationWorkflow,
    SystemTaskRunner,
    ManualWorkflow,
    submit_post_for_indexing,
    calculate_next_run_delta,
    send_schedule_notification,
)
from Asistent.schedule.strategies import (
    PromptScheduleStrategy,
    SystemScheduleStrategy,
    ManualScheduleStrategy,
)
# Импорт моделей расписаний (через __getattr__ из models.py)
from Asistent.models import AISchedule, AIScheduleRun
from blog.models import Post
from Asistent.services.agent_task_runner import execute_agent_task
from Asistent.services.notifications import (
    notify_authors_about_image,
    notify_author_error,
    notify_user,
)
from Asistent.services.telegram_client import get_telegram_client
from Asistent.services.task_execution import TaskExecutionContext

logger = logging.getLogger(__name__)


# Вспомогательная функция: эмулирует старый API async_task для обратной совместимости
def async_task(func_path: str, *args, task_name: str = '', hook=None, **kwargs):
    """
    Обёртка-совместимость для перехода c Django-Q API на Celery.
    Используется в местах, где ещё не переписан прямой вызов .delay().
    """
    import importlib
    # Разбиваем путь: 'Asistent.tasks.improve_author_draft_task' -> (модуль, функция)
    module_path, func_name = func_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    result = func.apply_async(args=args, kwargs=kwargs)
    return str(result.id)


STRATEGY_MAP = {
    'prompt': PromptScheduleStrategy,
    'system': SystemScheduleStrategy,
    'manual': ManualScheduleStrategy,
}


def _run_agent_task(
    task_id: int,
    method_name: str,
    *,
    success_message: Optional[str] = None,
    message_builder: Optional[Callable[[Dict[str, Any]], str]] = None,
    metadata_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    persist_message: bool = True,
) -> Dict[str, Any]:
    """
    Унифицированный запуск методов AI-агента.
    """
    from .ai_agent import AIAgent

    agent = AIAgent()
    method = getattr(agent, method_name)

    return execute_agent_task(
        task_id,
        agent_method=method,
        success_message=success_message,
        message_extractor=message_builder,
        metadata_builder=metadata_builder,
        persist_message=persist_message,
    )


# ========================================================================

# ========================================================================
# Улучшение авторского черновика (совместимость с legacy-вызовами)
# ========================================================================
@shared_task(name='Asistent.tasks.improve_author_draft_task', bind=True, max_retries=3, default_retry_delay=60)
def improve_author_draft_task(
    post_id: int,
    style: str = "balanced",
    custom_prompt: str = "",
) -> Dict[str, Any]:
    """
    Улучшает HTML-черновик автора и сохраняет результат для ручной проверки.

    Совместимая обёртка для старых вызовов Django-Q:
    - обновляет поля ai_draft_original/ai_draft_improved/ai_improvement_status;
    - уведомляет автора по завершении;
    - устойчиво к ошибкам GigaChat.
    """
    from django.db import transaction
    from django.utils import timezone
    from django.utils.html import strip_tags

    from Asistent.gigachat_api import get_gigachat_client
    from blog.models import Post

    STYLE_HINTS = {
        "balanced": (
            "Сохрани баланс между информативностью, лёгкостью чтения и SEO. "
            "Добавь плавные переходы между абзацами и подчёркни ключевые мысли подзаголовками."
        ),
        "literary": (
            "Сделай повествование более художественным: используйте выразительные образы, метафоры, "
            "риторику и разнообразные синтаксические конструкции. Не злоупотребляй сложными оборотами."
        ),
        "seo": (
            "Сфокусируйся на SEO: усили ключевые фразы, добавь подзаголовки h2/h3, списки, короткие абзацы, "
            "но избегай переспама. Сохрани естественный тон и полезность."
        ),
        "emotional": (
            "Усили эмоциональность и мотивацию, добавь вдохновляющие примеры, обращение к читателю, "
            "но избегай чрезмерной патетики и клише."
        ),
    }

    logger.info("🛠️ AI-улучшение черновика #%s (style=%s)", post_id, style)

    try:
        post = Post.objects.select_related("author").get(pk=post_id)
    except Post.DoesNotExist:
        logger.error("❌ improve_author_draft_task: пост #%s не найден", post_id)
        return {"success": False, "error": "post_not_found"}

    if not (post.content and post.content.strip()):
        logger.warning("⚠️ improve_author_draft_task: у поста #%s пустой контент", post_id)
        notify_user(
            recipient=post.author,
            notification_type="system",
            title="AI не смог улучшить черновик",
            message="AI_DRAFT_IMPROVEMENT_ERROR: Черновик пустой, улучшение невозможно.",
            related_article=post,
        )
        return {"success": False, "error": "empty_content"}

    style_hint = STYLE_HINTS.get(style, STYLE_HINTS["balanced"])
    extra_requirements = (
        f"\nДополнительные пожелания автора: {custom_prompt.strip()}"
        if custom_prompt and custom_prompt.strip()
        else ""
    )

    prompt = (
        "Ты — профессиональный редактор женского онлайн-журнала. Улучши HTML-черновик, сохранив структуру, "
        "смысл и авторский голос. Исправь ошибки, усили логику, добавь связки и оптимизируй под читабельность. "
        "Не удаляй существующие <img>, ссылки и HTML-теги статьи.\n\n"
        f"Стиль улучшения: {style_hint}.{extra_requirements}\n\n"
        "Верни результат строго в формате JSON без пояснений и без Markdown:\n"
        '{\n'
        '  "improved_html": "<!-- здесь обновлённый HTML-текст -->",\n'
        '  "summary": "Кратко опиши, что улучшено (1-2 предложения).",\n'
        '  "notes": "Подробные рекомендации или список внесённых правок."\n'
        "}\n\n"
        "ОРИГИНАЛЬНЫЙ ЧЕРНОВИК (HTML):\n"
        f"{post.content}"
    )

    def _normalize_json(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                cleaned = cleaned[start : end + 1]
        return cleaned

    client = get_gigachat_client()

    try:
        response_raw = client.chat(prompt)
        response_json = _normalize_json(response_raw)
        payload = json.loads(response_json)
    except Exception as exc:
        logger.exception("❌ Ошибка GigaChat при улучшении поста #%s: %s", post_id, exc)
        notify_user(
            recipient=post.author,
            notification_type="system",
            title="AI не смог улучшить черновик",
            message=f"AI_DRAFT_IMPROVEMENT_ERROR: {exc}",
            related_article=post,
        )
        return {"success": False, "error": str(exc)}

    improved_html = (payload.get("improved_html") or "").strip()
    notes = (payload.get("notes") or "").strip()
    summary = (payload.get("summary") or notes or "").strip()

    if not improved_html:
        logger.error("❌ improve_author_draft_task: пустой результат улучшения для поста #%s", post_id)
        notify_user(
            recipient=post.author,
            notification_type="system",
            title="AI не смог улучшить черновик",
            message="AI_DRAFT_IMPROVEMENT_ERROR: Модель вернула пустой результат.",
            related_article=post,
        )
        return {"success": False, "error": "empty_result"}

    plain_preview = strip_tags(improved_html)
    preview_short = plain_preview[:180] + "…" if len(plain_preview) > 180 else plain_preview

    try:
        with transaction.atomic():
            fields_to_update = {
                "ai_draft_improved": improved_html,
                "ai_improvement_notes": notes or summary,
                "ai_improvement_style": style,
                "ai_improvement_status": "ready",
                "ai_draft_improvement_requested": True,
            }

            if not post.ai_draft_original:
                fields_to_update["ai_draft_original"] = post.content

            Post.objects.filter(pk=post.pk).update(**fields_to_update)
    except Exception as exc:
        logger.exception("❌ Ошибка сохранения результатов улучшения поста #%s: %s", post_id, exc)
        notify_user(
            recipient=post.author,
            notification_type="system",
            title="AI не смог сохранить улучшение",
            message=f"AI_DRAFT_IMPROVEMENT_ERROR: {exc}",
            related_article=post,
        )
        return {"success": False, "error": str(exc)}

    notify_user(
        recipient=post.author,
        notification_type="system",
        title="🤖 AI улучшил ваш черновик",
        message=(
            f"AI_DRAFT_IMPROVEMENT_READY:{post.id}\n"
            f"{summary or 'AI завершил улучшение черновика. Проверьте изменения перед публикацией.'}"
        ),
        related_article=post,
    )

    logger.info("✅ Улучшение черновика #%s завершено. Предпросмотр: %s", post_id, preview_short)
    return {
        "success": True,
        "post_id": post_id,
        "summary": summary,
        "notes": notes,
    }
# ========================================================================
# Генерация изображения для поста (ручной вызов из формы редактирования)
# ========================================================================
@shared_task(name='Asistent.tasks.generate_post_image_task', bind=True, max_retries=2, default_retry_delay=30)
def generate_post_image_task(post_id: int, image_prompt: str = '', requested_by_id: int = None):
    """
    Асинхронная задача генерации нового изображения для статьи.
    Создаёт уведомление с путями к новому и старому изображениям.
    """
    from blog.models import Post
    from .auto_media_fixer import AutoMediaFixer

    logger.info(f"🎨 Запущена генерация изображения для поста #{post_id}")

    try:
        post = Post.objects.select_related('author').get(id=post_id)
    except Post.DoesNotExist:
        logger.error(f"❌ generate_post_image_task: пост #{post_id} не найден")
        return {'success': False, 'error': 'post_not_found'}

    old_image = getattr(post.kartinka, 'name', '') or None

    fixer = AutoMediaFixer()
    success, message, new_filepath = fixer.generate_new_image(
        post,
        custom_image_prompt=image_prompt or None,
    )

    if not success or not new_filepath:
        logger.warning(
            f"⚠️ generate_post_image_task: не удалось сгенерировать изображение для поста #{post_id} — {message}. "
            "Пробуем подобрать подходящую картинку."
        )
        fallback_success, fallback_message = fixer.fix_missing_media(
            post,
            is_superuser=False,
            strategy="download",
        )
        if fallback_success:
            post.save(update_fields=['kartinka'])
            notify_authors_about_image(
                post=post,
                new_image_path=getattr(post.kartinka, 'name', None),
                old_image_path=old_image,
                message=fallback_message,
                requested_by_id=requested_by_id,
            )
            return {
                'success': True,
                'post_id': post_id,
                'image_path': getattr(post.kartinka, 'name', None),
                'old_image': old_image,
                'message': fallback_message,
            }

        logger.error(
            f"❌ generate_post_image_task: не удалось ни сгенерировать, ни подобрать изображение для поста #{post_id} — {message}; {fallback_message}"
        )
        notify_author_error(post=post, error_message=fallback_message or message)
        return {'success': False, 'error': fallback_message or message}

    notify_authors_about_image(
        post=post,
        new_image_path=new_filepath,
        old_image_path=old_image,
        message=image_prompt or 'auto',
        requested_by_id=requested_by_id,
    )

    logger.info(f"✅ generate_post_image_task: новое изображение {new_filepath} сгенерировано для поста #{post_id}")
    return {
        'success': True,
        'post_id': post_id,
        'image_path': new_filepath,
        'old_image': old_image,
        'message': message,
    }
# ========================================================================
# ЕЖЕДНЕВНЫЕ ОТЧЁТЫ В TELEGRAM
# ========================================================================
@shared_task(name='Asistent.tasks.daily_telegram_seo_report')
def daily_telegram_seo_report():
    """
    Отправляет краткий отчёт в Telegram (утро/вечер) о проделанной SEO-работе.
    
    Примечание: переписано для Celery. Использует django_celery_results вместо django_q.
    """
    from django_celery_results.models import TaskResult
    from django.utils import timezone
    from django.conf import settings

    try:
        since = timezone.now() - timedelta(hours=12)
        recent = TaskResult.objects.filter(date_done__gte=since).order_by('-date_done')[:50]
        processed = recent.count()

        count_auto = recent.filter(task_name__icontains='auto_seo_optimize_new_articles').count()
        count_refresh = recent.filter(task_name__icontains='refresh_old_articles_task').count()
        count_submit = recent.filter(task_name__icontains='submit_new_posts_to_search_engines').count()
        count_media = recent.filter(task_name__icontains='bulk_media_images_indexing').count()

        top_lines = [
            f"Задач выполнено: {processed}",
            f"SEO новые: {count_auto} | Старые: {count_refresh} | Submit: {count_submit} | Media: {count_media}"
        ]

        text = "\n".join([
            "📬 Ежедневный отчёт SEO-автомата",
            *top_lines
        ])

        # Отправка напрямую через Telegram Bot API
        chat_id = getattr(settings, 'CHAT_ID8', '')  # @LukInterLab_News
        if chat_id:
            client = get_telegram_client()
            if client.send_message(chat_id, text):
                logger.info("✅ Отчёт отправлен в Telegram")
            else:
                logger.error("❌ Ошибка отправки отчёта в Telegram")

        return {'success': True, 'message': 'report_sent'}
    except Exception as e:
        logger.error(f"❌ daily_telegram_seo_report: {e}")
        return {'success': False, 'error': str(e)}
# ========================================================================
# ОБРАБОТЧИКИ КОМАНД AI-АГЕНТА
# ========================================================================
@shared_task(name='Asistent.tasks.execute_show_knowledge', bind=True, max_retries=2)
def execute_show_knowledge(task_id: int):
    """
    Обработчик команды: показать базу знаний
    Отображает записи из AIKnowledgeBase по категории или все
    """
    context: Optional[TaskExecutionContext] = None
    try:
        from .models import AIKnowledgeBase

        context = TaskExecutionContext.start(task_id)
        task = context.task
        
        logger.info(f"📚 Выполнение show_knowledge для задачи #{task_id}")
        
        # Получаем параметры
        category = task.parameters.get('category')
        
        # Фильтруем записи
        items = AIKnowledgeBase.objects.filter(is_active=True)
        
        if category:
            items = items.filter(category=category)
            title = f"📚 База знаний - {dict(AIKnowledgeBase.CATEGORY_CHOICES).get(category, category).title()}"
        else:
            title = "📚 База знаний - Все категории"
        
        items = items.order_by('-priority', '-usage_count')
        total = items.count()
        
        if total == 0:
            result_message = "❌ Записи не найдены"
        else:
            # Формируем ответ
            lines = [f"{title}\n", f"📊 Всего записей: {total}\n\n"]
            
            # Группируем по категориям
            if category:
                # Одна категория
                lines.append(f"📁 **{dict(AIKnowledgeBase.CATEGORY_CHOICES).get(category, category).title()}:**\n")
                for item in items[:20]:  # Ограничиваем 20 записями
                    lines.append(f"  • {item.title}")
                    lines.append(f"    💬 {item.content[:100]}...")
                    lines.append(f"    🔢 Использовано: {item.usage_count} раз\n")
            else:
                # Все категории
                for cat, display in AIKnowledgeBase.CATEGORY_CHOICES:
                    cat_items = items.filter(category=cat)[:5]
                    if cat_items.exists():
                        lines.append(f"\n📁 **{display}:**\n")
                        for item in cat_items:
                            lines.append(f"  • {item.title} (использовано: {item.usage_count})")
            
            result_message = "\n".join(lines)
        
        # Сохраняем результат в задаче
        context.complete(
            message=result_message,
            metadata={'category': category, 'total': total},
            result={
                'status': 'completed',
                'message': result_message,
                'total': total,
                'category': category,
            },
        )

        logger.info("✅ show_knowledge завершён: %s записей показано", total)
        return {'success': True, 'total': total}
        
    except Exception as e:
        logger.error("❌ Ошибка execute_show_knowledge: %s", e, exc_info=True)
        if context:
            context.fail(str(e))
        return {'success': False, 'error': str(e)}
# ========================================================================
# Обработчик команды: добавить запись в базу знаний
# ========================================================================
@shared_task(name='Asistent.tasks.execute_add_knowledge', bind=True, max_retries=2)
def execute_add_knowledge(task_id: int):
    """
    Обработчик команды: добавить запись в базу знаний
    """
    context: Optional[TaskExecutionContext] = None
    try:
        from .models import AIKnowledgeBase
        
        context = TaskExecutionContext.start(task_id)
        task = context.task
        
        logger.info(f"📝 Выполнение add_knowledge для задачи #{task_id}")
        
        # Получаем параметры
        category = task.parameters.get('category', 'правила')
        content = task.parameters.get('content', '')
        
        if not content:
            raise ValueError("Контент не указан")
        
        # Создаём запись
        # Генерируем заголовок из первых 50 символов контента
        title = content[:50] + ('...' if len(content) > 50 else '')
        
        knowledge = AIKnowledgeBase.objects.create(
            category=category,
            title=title,
            content=content,
            tags=[],
            priority=50,
            is_active=True,
            created_by=task.conversation.user
        )
        
        result_message = f"✅ Добавлено в базу знаний!\n\n📁 Категория: {dict(AIKnowledgeBase.CATEGORY_CHOICES).get(category)}\n📝 ID: {knowledge.id}\n\n{content[:200]}..."
        
        # Сохраняем результат
        context.complete(
            message=result_message,
            metadata={'knowledge_id': knowledge.id},
            result={'status': 'completed', 'knowledge_id': knowledge.id},
        )
        
        logger.info("✅ add_knowledge завершён: запись #%s", knowledge.id)
        return {'success': True, 'knowledge_id': knowledge.id}
        
    except Exception as e:
        logger.error("❌ Ошибка execute_add_knowledge: %s", e, exc_info=True)
        if context:
            context.fail(str(e))
        return {'success': False, 'error': str(e)}
# ========================================================================
# Обработчик команды: показать все расписания AI
# ========================================================================
@shared_task(name='Asistent.tasks.execute_manage_schedules', bind=True, max_retries=2)
def execute_manage_schedules(task_id: int):
    """Показать все расписания AI"""
    context: Optional[TaskExecutionContext] = None
    try:
        from .models import AISchedule
        
        context = TaskExecutionContext.start(task_id)
        
        schedules = AISchedule.objects.all().order_by('-is_active', 'name')
        
        lines = [f"📅 Расписания AI-генерации\n", f"📊 Всего: {schedules.count()}\n\n"]
        
        for schedule in schedules:
            status = "✅ Активно" if schedule.is_active else "⏸️ Выключено"
            lines.append(f"#{schedule.id} {status} - {schedule.name}")
            lines.append(f"   📂 Категория: {schedule.category.title if schedule.category else 'Нет'}")
            lines.append(f"   ⏰ Частота: {schedule.get_posting_frequency_display()}")
            lines.append(f"   📝 Статей: {schedule.posts_per_run}\n")
        
        result_message = "\n".join(lines)
        
        context.complete(
            message=result_message,
            result={'status': 'completed', 'total': schedules.count()},
        )
        
        return {'success': True}
    except Exception as e:
        logger.error("❌ execute_manage_schedules: %s", e, exc_info=True)
        if context:
            context.fail(str(e))
        return {'success': False, 'error': str(e)}
# ========================================================================
# Обработчик команды: запустить конкретное расписание
# ========================================================================  
@shared_task(name='Asistent.tasks.execute_run_schedule', bind=True, max_retries=2)
def execute_run_schedule(task_id: int):
    """Запустить конкретное расписание"""
    context: Optional[TaskExecutionContext] = None
    try:
        from .models import AISchedule, AIConversation, AIMessage
        from django.contrib.auth.models import User
        
        context = TaskExecutionContext.start(task_id)
        task = context.task
        
        schedule_id = task.parameters.get('schedule_id')
        if not schedule_id:
            raise ValueError("schedule_id не указан")
        
        # Используем filter().first() вместо get() для graceful fallback
        schedule = AISchedule.objects.filter(id=schedule_id, is_active=True).first()
        
        if not schedule:
            error_msg = f"AISchedule ID={schedule_id} не найдено или неактивно"
            logger.error(f"❌ execute_run_schedule: {error_msg}")
            
            # Отправляем уведомление в AI-чат
            admin = User.objects.filter(is_superuser=True).first()
            if admin:
                conversation, _ = AIConversation.objects.get_or_create(
                    admin=admin,
                    title='🔴 Мониторинг в реальном времени',
                    defaults={'is_active': True}
                )
                
                message = f"⚠️ ПРОБЛЕМА С РАСПИСАНИЕМ!\n\n"
                message += f"Расписание ID={schedule_id} не найдено или неактивно.\n"
                message += f"Задача AITask ID={task_id} не может быть выполнена.\n\n"
                message += f"💡 РЕШЕНИЕ:\n"
                message += f"  1. Проверьте существование расписания в админке\n"
                message += f"  2. Удалите старые задачи Django-Q с несуществующими ID\n"
                message += f"  3. Запустите: python manage.py sync_schedules --force\n"
                
                AIMessage.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=message
                )
            
            if context:
                context.fail(error_msg)
            return {'success': False, 'error': 'schedule_not_found', 'schedule_id': schedule_id}
        
        # Импортируем функцию запуска расписания
        from .daily_article_generator import run_specific_schedule
        
        result = run_specific_schedule(schedule_id)
        
        result_message = f"✅ Расписание '{schedule.name}' запущено!\n\n{result.get('message', 'Выполнено успешно')}"
        
        context.complete(
            message=result_message,
            metadata={'schedule_id': schedule_id},
            result=result,
        )
        
        return result
    except Exception as e:
        logger.error("❌ execute_run_schedule: %s", e, exc_info=True)
        if context:
            context.fail(str(e))
        return {'success': False, 'error': str(e)}
# ========================================================================
# Обработчик команды: синхронизировать расписания с Django-Q
# ========================================================================
@shared_task(name='Asistent.tasks.execute_sync_schedules', bind=True, max_retries=2)
def execute_sync_schedules(task_id: int):
    """Синхронизировать расписания с Django-Q"""
    context: Optional[TaskExecutionContext] = None
    try:
        from .models import AISchedule
        
        context = TaskExecutionContext.start(task_id)
        
        # Пересоздаём все расписания
        synced = 0
        for schedule in AISchedule.objects.filter(is_active=True):
            # Триггерим сигнал повторным сохранением
            schedule.save()
            synced += 1
        
        result_message = f"✅ Синхронизировано {synced} активных расписаний с Django-Q"
        
        context.complete(
            message=result_message,
            result={'status': 'completed', 'synced': synced},
        )
        
        return {'success': True, 'synced': synced}
    except Exception as e:
        logger.error("❌ execute_sync_schedules: %s", e, exc_info=True)
        if context:
            context.fail(str(e))
        return {'success': False, 'error': str(e)}

"""         ОБРАБОТЧИКИ РЕКЛАМНЫХ КОМАНД                         """
# ========================================================================
@shared_task(name='Asistent.tasks.execute_ad_show_places', bind=True, max_retries=2)
def execute_ad_show_places(task_id: int):
    """Показать рекламные места через AI-агента"""
    return _run_agent_task(task_id, "_execute_ad_show_places")

# ========================================================================
@shared_task(name='Asistent.tasks.execute_ad_statistics', bind=True, max_retries=2)
def execute_ad_statistics(task_id: int):
    """Статистика рекламы через AI-агента"""
    return _run_agent_task(task_id, "_execute_ad_statistics")

# ========================================================================
@shared_task(name='Asistent.tasks.execute_ad_list_banners', bind=True, max_retries=2)
def execute_ad_list_banners(task_id: int):
    """Список баннеров через AI-агента"""
    return _run_agent_task(task_id, "_execute_ad_list_banners")

# ========================================================================
@shared_task(name='Asistent.tasks.execute_ad_activate_banner', bind=True, max_retries=2)
def execute_ad_activate_banner(task_id: int):
    """Активировать баннер через AI-агента"""
    return _run_agent_task(task_id, "_execute_ad_activate_banner")

# ========================================================================
@shared_task(name='Asistent.tasks.execute_ad_deactivate_banner', bind=True, max_retries=2)
def execute_ad_deactivate_banner(task_id: int):
    """Деактивировать баннер через AI-агента"""
    return _run_agent_task(task_id, "_execute_ad_deactivate_banner")

# ========================================================================
@shared_task(name='Asistent.tasks.execute_ad_insert_in_article', bind=True, max_retries=2)
def execute_ad_insert_in_article(task_id: int):
    """Вставить рекламу в статью через AI-агента"""
    return _run_agent_task(task_id, "_execute_ad_insert_in_article")


"""         ОБРАБОТЧИКИ ГЕНЕРАЦИИ КОНТЕНТА                         """
# ========================================================================
# Обработчик команды: генерация статьи через AI-агента готовую логику из ai_agent.py
# ========================================================================
@shared_task(name='Asistent.tasks.execute_generate_article', bind=True, max_retries=2)
def execute_generate_article(task_id: int):
    """
    Генерация статьи через AI-агента
    Использует готовую логику из ai_agent.py
    """

    def _message(result: Dict[str, Any]) -> str:
        post_id = result.get('post_id')
        post_url = result.get('url', '')
        generation_time = result.get('generation_time', 0)
        return (
            "✅ Статья успешно создана и опубликована!\n"
            f"📰 ID статьи: {post_id}\n"
            f"🔗 Ссылка: {post_url}\n"
            f"⏱️ Время генерации: {generation_time}s\n"
            "🎉 Статья доступна на сайте!"
        )

    def _metadata(result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'task_id': task_id,
            'post_id': result.get('post_id'),
            'url': result.get('url'),
        }

    logger.info("📝 Выполнение generate_article для задачи #%s", task_id)
    result = _run_agent_task(
        task_id,
        "_execute_generate_article",
        message_builder=_message,
        metadata_builder=_metadata,
    )

    if result.get('success'):
        logger.info("✅ Статья #%s создана через AI-агента", result.get('post_id'))

    return result
# ========================================================================
# Обработчик команды: парсинг видео через AI-агента
# ========================================================================
@shared_task(name='Asistent.tasks.execute_parse_video', bind=True, max_retries=2)
def execute_parse_video(task_id: int):
    """Парсинг видео через AI-агента"""

    def _message(result: Dict[str, Any]) -> str:
        extra = result.get('message')
        return "✅ Видео обработано!" + (f"\n\n{extra}" if extra else "")

    return _run_agent_task(task_id, "_execute_parse_video", message_builder=_message)
# ========================================================================
# Обработчик команды: парсинг аудио через AI-агента
# ========================================================================
@shared_task(name='Asistent.tasks.execute_parse_audio', bind=True, max_retries=2)
def execute_parse_audio(task_id: int):
    """Парсинг аудио через AI-агента"""

    def _message(result: Dict[str, Any]) -> str:
        extra = result.get('message')
        return "✅ Аудио обработано!" + (f"\n\n{extra}" if extra else "")

    return _run_agent_task(task_id, "_execute_parse_audio", message_builder=_message)
# ========================================================================
# Обработчик команды: распределение бонусов через AI-агента
# ========================================================================
@shared_task(name='Asistent.tasks.execute_distribute_bonuses', bind=True, max_retries=2)
def execute_distribute_bonuses(task_id: int):
    """Распределение бонусов через AI-агента"""

    def _message(result: Dict[str, Any]) -> str:
        extra = result.get('message')
        return "✅ Бонусы распределены!" + (f"\n\n{extra}" if extra else "")

    return _run_agent_task(task_id, "_execute_distribute_bonuses", message_builder=_message)
         
'''         AI-РАСПИСАНИЯ: Автоматическая генерация статей                   '''

@shared_task(name='Asistent.tasks.run_specific_schedule', bind=True, max_retries=3)
def run_specific_schedule(schedule_id: int):
    """
    Прокси-функция для обратной совместимости.
    Перенаправляет вызов в новую реализацию в schedule/tasks.py
    
    Args:
        schedule_id: ID объекта AISchedule для выполнения
    
    Returns:
        dict: Результат выполнения с ключами success, created_posts, errors
    """
    from Asistent.schedule.tasks import run_specific_schedule as new_run_specific_schedule
    return new_run_specific_schedule(schedule_id)
# ========================================================================
# Вычисляет интервал до следующего запуска на основе частоты.
# ========================================================================
def _calculate_next_run_delta(frequency: str) -> timedelta:
    """Совместимость: использует новую реализацию в модуле расписаний."""
    return calculate_next_run_delta(frequency)

def run_system_task(schedule, now, task_name):
    """Совместимость: проксирует выполнение в новую инфраструктуру."""
    from Asistent.schedule.tasks import run_system_task as new_run_system_task
    return new_run_system_task(schedule, now, task_name)

def run_prompt_schedule(schedule, now):
    """Совместимость: проксирует выполнение в новую инфраструктуру."""
    from Asistent.schedule.tasks import run_prompt_schedule as new_run_prompt_schedule
    return new_run_prompt_schedule(schedule, now)
# ========================================================================
# Отправляет уведомление о выполнении расписания в Telegram.
# ========================================================================
def _send_schedule_notification(schedule, created_posts, success=True, error=None):
    """Совместимость: использует общий сервис отправки уведомлений."""
# ========================================================================
# Автоочистка системных логов (удаление логов старше 24 часов)
# ========================================================================
@shared_task(name='Asistent.tasks.clean_old_system_logs')
def clean_old_system_logs():
    """
    Удаляет логи старше 24 часов из базы данных.
    Вызывается автоматически через Django-Q расписание.
    """
    try:
        from Asistent.models import SystemLog
        
        cutoff_time = timezone.now() - timedelta(hours=24)
        deleted_count, _ = SystemLog.objects.filter(timestamp__lt=cutoff_time).delete()
        
        logger.info(f"Очистка логов: удалено {deleted_count} записей старше 24 часов")
        return {'deleted': deleted_count, 'cutoff_time': cutoff_time.isoformat()}
        
    except Exception as e:
        logger.error(f"Ошибка при очистке старых логов: {e}", exc_info=True)
        return {'error': str(e)}

def _analyze_delay_with_gigachat(
    current_delay: int,
    rate_limit_hits: int,
    queue_length: int,
    recent_errors: list
    ) -> int:
    """
    Использует GigaChat для анализа ситуации и определения оптимальной задержки.
    Возвращает рекомендуемую задержку в секундах.
    """
    try:
        from Asistent.gigachat_api import get_gigachat_client
        
        client = get_gigachat_client()
        
        analysis_prompt = f"""Ты - AI-аналитик системы генерации гороскопов.

        Текущая ситуация:
        - Текущая задержка между задачами: {current_delay} секунд
        - Количество попаданий в rate limit за последний час: {rate_limit_hits}
        - Длина очереди задач: {queue_length}
        - Последние ошибки: {len(recent_errors)} ошибок

        Проанализируй ситуацию и определи оптимальную задержку между выполнением задач генерации гороскопов.

        Учитывай:
        1. Нужно избежать ошибок 429 (Too Many Requests)
        2. Нужно обеспечить стабильную работу системы
        3. Задачи должны выполняться последовательно
        4. Система должна быть устойчива к нагрузке

        Ответь ТОЛЬКО числом (количество секунд задержки), без дополнительных объяснений.
        Рекомендуемый диапазон: 30-120 секунд."""

        try:
            response = client.chat(message=analysis_prompt)
            # Пытаемся извлечь число из ответа
            import re
            numbers = re.findall(r'\d+', str(response))
            if numbers:
                recommended_delay = int(numbers[0])
                # Ограничиваем разумными пределами
                recommended_delay = max(30, min(120, recommended_delay))
                logger.info(f"   🤖 GigaChat рекомендует задержку: {recommended_delay} сек")
                return recommended_delay
        except Exception as e:
            logger.warning(f"   ⚠️ Не удалось получить рекомендацию от GigaChat: {e}")
    except Exception as e:
        logger.warning(f"   ⚠️ Ошибка при анализе через GigaChat: {e}")
    
    # Fallback: базовая логика
    if rate_limit_hits > 3:
        return min(120, current_delay + 30)
    elif rate_limit_hits > 1:
        return min(90, current_delay + 15)
    elif queue_length > 5:
        return 75
    else:
        return current_delay
