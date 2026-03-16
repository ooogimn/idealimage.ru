import os
import logging
from celery import shared_task
from django.core.files import File
from django.conf import settings
from blog.models import Post
from blog.utils_video_processing import (
    optimize_video, 
    create_video_poster, 
    create_video_preview,
    get_video_info
)
from utilits.image_optimizer import ImageOptimizer

logger = logging.getLogger(__name__)

@shared_task(name='blog.tasks.process_media_task')
def process_media_task(post_id):
    """
    Асинхронная задача для полной обработки медиа поста (видео или фото):
    1. Для видео: Оптимизация, постер, 5-сек превью, удаление оригинала.
    2. Для фото: Конвертация в WebP, создание thumbnail.
    """
    try:
        post = Post.objects.get(pk=post_id)
    except Post.DoesNotExist:
        logger.error(f"Post with id {post_id} not found for media processing")
        return

    if not post.kartinka:
        logger.warning(f"Post {post_id} has no file in 'kartinka'")
        return

    try:
        file_path = post.kartinka.path
        if not os.path.exists(file_path):
            logger.error(f"File not found at {file_path}")
            return
    except NotImplementedError:
        # Для удаленных хранилищ (S3 и т.д.) путь через .path может не работать
        # Но здесь скорее всего локальное хранилище
        logger.error(f"Could not get local path for post {post_id}. Remote storage not handled yet.")
        return

    ext = os.path.splitext(file_path)[1].lower()
    is_video = ext in ['.mp4', '.webm', '.mov', '.avi', '.mkv']
    is_image = ext in ['.jpg', '.jpeg', '.png', '.webp', '.avif']

    if is_video:
        _handle_video(post, file_path, ext)
    elif is_image:
        _handle_image(post, file_path)

def _handle_video(post, video_path, ext):
    """Логика обработки видео"""
    # Устанавливаем статус "Обрабатывается"
    post.video_processing_status = 'processing'
    post.save(update_fields=['video_processing_status'])

    try:
        logger.info(f"🚀 Начало обработки видео для поста {post.id}: {post.title}")
        
        # 1. Получаем инфо (длительность)
        video_info = get_video_info(video_path)
        if video_info:
            post.video_duration = video_info.get('duration')

        # 2. Создаем постер (если еще нет)
        if not post.video_poster:
            poster_path = create_video_poster(video_path)
            if poster_path and os.path.exists(poster_path):
                with open(poster_path, 'rb') as f:
                    post.video_poster.save(
                        f"poster_{post.slug or post.id}.jpg",
                        File(f),
                        save=False
                    )
                try: os.remove(poster_path)
                except: pass
            logger.info(f"✅ Постер для поста {post.id} создан")

        # 3. Создаем 5-сек превью (если еще нет)
        if not post.video_preview:
            preview_path = create_video_preview(video_path)
            if preview_path and os.path.exists(preview_path):
                with open(preview_path, 'rb') as f:
                    post.video_preview.save(
                        f"preview_{post.slug or post.id}.mp4",
                        File(f),
                        save=False
                    )
                try: os.remove(preview_path)
                except: pass
            logger.info(f"✅ Превью для поста {post.id} создано")

        # 4. Оптимизация видео
        if not post.video_optimized:
            optimized_path = optimize_video(video_path)
            
            if optimized_path and os.path.exists(optimized_path) and optimized_path != video_path:
                original_size = os.path.getsize(video_path)
                optimized_size = os.path.getsize(optimized_path)
                
                logger.info(f"📊 Оптимизация {post.id}: {original_size/1024/1024:.2f}MB -> {optimized_size/1024/1024:.2f}MB")
                
                storage = post.kartinka.storage
                old_relative_path = post.kartinka.name
                
                # Сохраняем оптимизированное видео на место оригинала
                with open(optimized_path, 'rb') as f:
                    new_name = f"video_{post.slug or post.id}{ext}"
                    post.kartinka.save(new_name, File(f), save=False)
                
                # Удаляем старый громоздкий файл безвозвратно
                try:
                    if old_relative_path != post.kartinka.name:
                        storage.delete(old_relative_path)
                        logger.info(f"🗑️ Оригинал {old_relative_path} удален")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось удалить оригинал {old_relative_path}: {e}")
                
                try: os.remove(optimized_path)
                except: pass
                
                post.video_optimized = True
            else:
                logger.info(f"ℹ️ Оптимизация не потребовалась или файл уже оптимален для поста {post.id}")
        
        post.video_processing_status = 'completed'
        post.save()
        logger.info(f"✅ Обработка видео для поста {post.id} успешно завершена")

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке видео для поста {post.id}: {e}", exc_info=True)
        post.video_processing_status = 'failed'
        post.save(update_fields=['video_processing_status'])

def _handle_image(post, image_path):
    """Логика обработки изображений"""
    logger.info(f"🖼️ Обработка изображения для поста {post.id}: {post.title}")
    
    try:
        # 1. Создаем thumbnail
        if not post.thumbnail:
            # Используем ImageOptimizer для создания thumbnail
            thumb_content, thumb_ext = ImageOptimizer.create_thumbnail(image_path)
            if thumb_content:
                post.thumbnail.save(
                    f"thumb_{post.slug or post.id}.{thumb_ext}",
                    thumb_content,
                    save=False
                )
                logger.info(f"✅ Thumbnail для поста {post.id} создан")

        # 2. Оптимизируем основное изображение (конвертация в WebP)
        # Если файл еще не webp
        if not image_path.lower().endswith('.webp'):
            relative_webp = ImageOptimizer.optimize_and_convert_to_webp(
                image_path, 
                context_name=post.title,
                max_width=1600, 
                max_height=1200
            )
            if relative_webp:
                # Обновляем поле kartinka
                post.kartinka.name = relative_webp
                logger.info(f"✅ Изображение поста {post.id} конвертировано в WebP")
        
        post.save()
        logger.info(f"✅ Обработка изображения для поста {post.id} завершена")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке изображения для поста {post.id}: {e}", exc_info=True)
