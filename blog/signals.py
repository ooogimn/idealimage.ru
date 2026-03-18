from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Post
from .tasks import process_media_task
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Post)
def post_save_media_processing(sender, instance, created, **kwargs):
    return  # DISABLED_HOTFIX_2026_03_18
    """
    Сигнал для запуска обработки медиа (видео/фото) после сохранения поста
    """
    if not instance.kartinka:
        return

    name = instance.kartinka.name.lower()
    is_video = any(name.endswith(ext) for ext in ['.mp4', '.webm', '.mov', '.avi', '.mkv'])
    is_image = any(name.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.avif'])
    
    # Для видео - проверяем статус
    if is_video and instance.video_processing_status == 'pending':
        logger.info(f"Signal: Triggering video processing for post {instance.id}")
        process_media_task.apply_async(args=[instance.id], countdown=2)
    
    # Для фото - проверяем наличие thumbnail или формат (если не webp)
    elif is_image:
        if not instance.thumbnail or not name.endswith('.webp'):
            # Проверяем, не запущена ли уже задача (опционально, но здесь просто пушим)
            # Для фото можно не использовать статус pending, а просто проверять наличие полей
            logger.info(f"Signal: Triggering image processing for post {instance.id}")
            process_media_task.apply_async(args=[instance.id], countdown=2)

