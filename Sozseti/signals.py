"""
Signals для автоматической публикации в соцсети
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from blog.models import Post

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Post)
def auto_publish_to_social(sender, instance, created, **kwargs):
    # Условие 0: при программном сохранении (например, в AI-генераторе)
    # можно явно отключить автопубликацию на уровне объекта.
    if getattr(instance, '_skip_auto_publication', False):
        return

    """
    Автоматическая постановка задачи на публикацию статьи в соцсети после публикации.
    """
    # Условие 1: статья должна быть опубликована
    if instance.status != 'published':
        return

    # Условие 2: автопубликация включена
    if not getattr(instance, 'auto_publish_social', False):
        return

    # Условие 3: уже опубликовано или стоит флаг fixed — считаем, что рассылка выполнена
    if instance.fixed or instance.telegram_posted_at:
        logger.debug("⏭️ Автопубликация пропущена для '%s' — fixed=%s, telegram_posted_at=%s",
                     instance.title, instance.fixed, instance.telegram_posted_at)
        return

    # Условие 4: чтобы избежать бесконечных ретраев, убедимся, что есть хотя бы изображение или описание
    has_media = bool(getattr(instance, 'kartinka', None))
    if not has_media and not instance.description:
        logger.info("⏭️ Автопубликация пропущена для '%s' — нет изображения и описания", instance.title)
        return

    try:
        from Sozseti.tasks import publish_post_to_social

        post_id = instance.id
        task_name = f"auto_social_post_{post_id}"

        def _enqueue_social_publish():
            publish_post_to_social.apply_async(args=[post_id])

        # Запускаем только после успешного коммита транзакции.
        transaction.on_commit(_enqueue_social_publish)
        logger.info("🗓️ Запланирована автопубликация статьи '%s' (task=%s)", instance.title, task_name)
    except Exception as exc:
        logger.error("❌ Не удалось поставить автопубликацию '%s' в очередь: %s", instance.title, exc)
