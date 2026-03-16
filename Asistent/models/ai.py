"""
Модели для AI-ассистента

AIConversation - История диалогов
AIMessage - Сообщения в диалоге
AITask - Задачи, поставленные через AI-чат
AIKnowledgeBase - База знаний AI-ассистента
AuthorNotification - Уведомления для авторов
"""
import logging
import hashlib
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.cache import cache


class AIConversation(models.Model):
    """История диалогов с AI-ассистентом"""
    
    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='ai_conversations',
        verbose_name='Администратор'
    )
    
    title = models.CharField(
        max_length=200,
        default='Новый диалог',
        verbose_name='Название диалога'
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен',
        help_text='Активный диалог отображается в списке'
    )
    
    class Meta:
        verbose_name = '🤖 AI-Агент: Диалоги'
        verbose_name_plural = '🤖 AI-Агент: Диалоги'
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.title} ({self.admin.username})"
    
    def get_messages_count(self):
        """Количество сообщений в диалоге"""
        return self.messages.count()
    
    def get_last_message(self):
        """Последнее сообщение в диалоге"""
        return self.messages.order_by('-timestamp').first()


class AIMessage(models.Model):
    """Сообщения в диалоге с AI"""
    
    ROLE_CHOICES = [
        ('admin', 'Администратор'),
        ('assistant', 'AI-ассистент'),
        ('system', 'Система'),
    ]
    
    conversation = models.ForeignKey(
        AIConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Диалог'
    )
    
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        verbose_name='Роль'
    )
    
    content = models.TextField(
        verbose_name='Содержание сообщения'
    )
    
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Время отправки'
    )
    
    metadata = models.JSONField(
        default=dict,
        verbose_name='Метаданные',
        help_text='Дополнительная информация: задачи, команды, результаты'
    )
    
    embedding = models.JSONField(
        null=True,
        blank=True,
        verbose_name='Векторное представление',
        help_text='Для поиска похожих диалогов (генерируется для admin-сообщений)'
    )
    
    class Meta:
        verbose_name = '🤖 AI-Агент: Сообщения'
        verbose_name_plural = '🤖 AI-Агент: Сообщения'
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['conversation', 'timestamp'], name='aimsg_conv_time_idx'),
            models.Index(fields=['role', 'timestamp'], name='aimsg_role_time_idx'),
        ]
    
    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:50]}..."


class AITask(models.Model):
    """Задачи, поставленные через AI-чат"""
    
    STATUS_CHOICES = [
        ('pending', 'В очереди'),
        ('in_progress', 'Выполняется'),
        ('completed', 'Выполнено'),
        ('failed', 'Ошибка'),
        ('cancelled', 'Отменено'),
    ]
    
    TASK_TYPE_CHOICES = [
        ('generate_article', 'Генерация статьи'),
        ('parse_video', 'Парсинг видео'),
        ('parse_audio', 'Парсинг аудио'),
        ('distribute_bonuses', 'Распределение бонусов'),
        ('optimize_schedule', 'Оптимизация расписания'),
        # Социальные сети
        ('publish_to_social', 'Публикация в соцсети'),
        ('schedule_posts', 'Создание расписания публикаций'),
        ('reply_to_comment', 'Ответ на комментарий в соцсети'),
        ('reply_to_message', 'Ответ в переписке'),
        ('analyze_channel', 'Анализ канала'),
        ('optimize_posting', 'Оптимизация времени публикации'),
        ('create_ad_campaign', 'Создание рекламной кампании'),
        ('crosspost_content', 'Кросс-постинг контента'),
        # Реклама
        ('ad_show_places', 'Показать рекламные места'),
        ('ad_statistics', 'Статистика рекламы'),
        ('ad_activate_banner', 'Активировать баннер'),
        ('ad_deactivate_banner', 'Деактивировать баннер'),
        ('ad_list_banners', 'Список баннеров'),
        ('ad_insert_in_article', 'Вставить рекламу в статью'),
    ]
    
    conversation = models.ForeignKey(
        AIConversation,
        on_delete=models.CASCADE,
        related_name='tasks',
        verbose_name='Диалог'
    )
    
    command = models.CharField(
        max_length=500,
        verbose_name='Исходная команда',
        help_text='Команда от администратора'
    )
    
    task_type = models.CharField(
        max_length=50,
        choices=TASK_TYPE_CHOICES,
        verbose_name='Тип задачи'
    )
    
    parameters = models.JSONField(
        default=dict,
        verbose_name='Параметры',
        help_text='Параметры выполнения задачи'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Статус'
    )
    
    progress_description = models.TextField(
        blank=True,
        verbose_name='Описание прогресса',
        help_text='Текущее состояние выполнения'
    )
    
    result = models.JSONField(
        null=True,
        blank=True,
        verbose_name='Результат',
        help_text='Результат выполнения задачи'
    )
    
    error_message = models.TextField(
        blank=True,
        verbose_name='Сообщение об ошибке'
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата начала выполнения'
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата завершения'
    )
    
    class Meta:
        verbose_name = '🤖 AI-Агент: Задачи'
        verbose_name_plural = '🤖 AI-Агент: Задачи'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.get_task_type_display()} - {self.get_status_display()}"
    
    def start(self):
        """Начать выполнение задачи"""
        self.status = 'in_progress'
        self.started_at = timezone.now()
        self.save()
    
    def complete(self, result=None):
        """Завершить задачу успешно"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        if result:
            self.result = result
        self.save()
    
    def fail(self, error_message):
        """Завершить задачу с ошибкой"""
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save()


class AIKnowledgeBase(models.Model):
    """База знаний AI-ассистента"""
    
    CATEGORY_CHOICES = [
        ('промпты', 'Промпты'),
        ('правила', 'Правила'),
        ('примеры', 'Примеры'),
        ('команды', 'Команды'),
        ('faq', 'Частые вопросы'),
        ('инструкции', 'Инструкции'),
        ('источники', 'Источники'),
    ]
    
    category = models.CharField(
        max_length=100,
        choices=CATEGORY_CHOICES,
        verbose_name='Категория'
    )
    
    title = models.CharField(
        max_length=300,
        verbose_name='Заголовок'
    )
    
    content = models.TextField(
        verbose_name='Содержание'
    )
    
    tags = models.JSONField(
        default=list,
        verbose_name='Теги',
        help_text='Список тегов для поиска'
    )
    
    embedding = models.JSONField(
        null=True,
        blank=True,
        verbose_name='Векторное представление',
        help_text='Для семантического поиска (опционально)'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )
    
    usage_count = models.IntegerField(
        default=0,
        verbose_name='Количество использований'
    )
    
    priority = models.IntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name='Приоритет',
        help_text='0-100, чем выше - тем важнее (используется первым)'
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='knowledge_entries',
        verbose_name='Создал'
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Дата обновления'
    )
    
    class Meta:
        verbose_name = '🤖 AI-Агент: База знаний'
        verbose_name_plural = '🤖 AI-Агент: База знаний'
        ordering = ['-priority', '-usage_count', '-created_at']
        indexes = [
            models.Index(fields=['category', '-priority'], name='kb_cat_prior_idx'),
            models.Index(fields=['-usage_count'], name='kb_usage_idx'),
            models.Index(fields=['is_active', 'category'], name='kb_active_cat_idx'),
            models.Index(fields=['-created_at'], name='kb_created_idx'),
        ]
    
    def __str__(self):
        return f"{self.get_category_display()}: {self.title}"
    
    def increment_usage(self):
        """Увеличить счетчик использований"""
        self.usage_count += 1
        self.save(update_fields=['usage_count'])
    
    @staticmethod
    def find_similar(query_text, top_k=5, category=None, min_similarity=0.0, use_cache=True):
        """
        Находит топ-K наиболее похожих записей по векторному сходству
        """
        logger = logging.getLogger(__name__)
        
        # Формируем ключ кэша
        cache_key = None
        if use_cache:
            cache_hash = hashlib.md5(
                f"{query_text}:{top_k}:{category}:{min_similarity}".encode()
            ).hexdigest()
            cache_key = f"kb_search:{cache_hash}"
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.info(f"✅ Найдено {len(cached_result)} записей из кэша")
                return cached_result
        
        try:
            # Генерируем embedding запроса
            from Asistent.gigachat_api import get_embeddings
            import numpy as np
            
            query_embedding = np.array(get_embeddings(query_text))
            
            if len(query_embedding) == 0:
                logger.warning("Не удалось получить embedding для запроса, используем текстовый поиск")
                result = AIKnowledgeBase._fallback_text_search(query_text, top_k, category)
                if use_cache and cache_key:
                    cache.set(cache_key, result, timeout=300)
                return result
            
            # Оптимизация: используем пагинацию для больших наборов данных
            items_query = AIKnowledgeBase.objects.filter(
                is_active=True,
                embedding__isnull=False
            ).exclude(embedding=[]).only('id', 'title', 'content', 'embedding', 'usage_count')
            
            if category:
                items_query = items_query.filter(category=category)
            
            # Ограничиваем выборку разумным числом
            items = items_query.order_by('-priority', '-usage_count')[:100]
            
            similarities = []
            batch_size = 20
            
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                
                for item in batch:
                    try:
                        item_embedding = np.array(item.embedding)
                        
                        if item_embedding.shape != query_embedding.shape:
                            continue
                        
                        # Косинусная близость
                        dot_product = np.dot(query_embedding, item_embedding)
                        norm_query = np.linalg.norm(query_embedding)
                        norm_item = np.linalg.norm(item_embedding)
                        
                        if norm_query == 0 or norm_item == 0:
                            continue
                        
                        similarity = dot_product / (norm_query * norm_item)
                        
                        if similarity >= min_similarity:
                            similarities.append((item, float(similarity)))
                            
                    except Exception as e:
                        logger.warning(f"Ошибка расчёта similarity для {item.id}: {e}")
                        continue
            
            similarities.sort(key=lambda x: x[1], reverse=True)
            
            for item, _ in similarities[:top_k]:
                item.increment_usage()
            
            result = similarities[:top_k]
            
            if use_cache and cache_key:
                cache.set(cache_key, result, timeout=300)
            
            logger.info(f"✅ Найдено {len(result)} похожих записей")
            return result
            
        except ImportError as e:
            logger.error(f"Ошибка импорта numpy: {e}")
            result = AIKnowledgeBase._fallback_text_search(query_text, top_k, category)
            if use_cache and cache_key:
                cache.set(cache_key, result, timeout=300)
            return result
            
        except Exception as e:
            logger.error(f"Ошибка векторного поиска: {e}")
            result = AIKnowledgeBase._fallback_text_search(query_text, top_k, category)
            if use_cache and cache_key:
                cache.set(cache_key, result, timeout=300)
            return result
    
    @staticmethod
    def _fallback_text_search(query_text, top_k=5, category=None):
        """Резервный текстовый поиск при недоступности векторного"""
        logger = logging.getLogger(__name__)
        logger.info("🔍 Используем текстовый fallback поиск")
        
        words = query_text.lower().split()
        items = AIKnowledgeBase.objects.filter(is_active=True)
        
        if category:
            items = items.filter(category=category)
        
        results = []
        for item in items:
            text = f"{item.title} {item.content}".lower()
            
            if hasattr(item, 'tags') and item.tags:
                tags_text = " ".join(str(tag) for tag in item.tags)
                text += " " + tags_text.lower()
            
            matches = sum(1 for word in words if word in text)
            
            if matches > 0:
                similarity = min(matches / len(words), 1.0)
                results.append((item, similarity))
        
        results.sort(key=lambda x: x[1], reverse=True)
        
        for item, _ in results[:top_k]:
            item.increment_usage()
        
        return results[:top_k]


class AuthorNotification(models.Model):
    """Уведомления для авторов"""
    
    NOTIFICATION_TYPES = [
        ('task_available', 'Новое задание'),
        ('task_taken', 'Задание взято'),
        ('moderation_passed', 'Модерация пройдена'),
        ('moderation_failed', 'Модерация не пройдена'),
        ('task_approved', 'Задание одобрено'),
        ('task_rejected', 'Задание отклонено'),
        ('payment', 'Начисление средств'),
        ('system', 'Системное уведомление'),
    ]
    
    recipient = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name="Получатель",
    )
    notification_type = models.CharField(
        max_length=30,
        choices=NOTIFICATION_TYPES,
        verbose_name="Тип уведомления",
    )
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    message = models.TextField(verbose_name="Сообщение")
    related_task = models.ForeignKey(
        'Asistent.ContentTask',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name="Связанное задание",
    )
    related_article = models.ForeignKey(
        'blog.Post',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name="Связанная статья",
    )
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата прочтения")
    
    class Meta:
        verbose_name = "📬 Уведомления для авторов"
        verbose_name_plural = "📬 Уведомления для авторов"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.recipient.username} - {self.title}"
    
    def mark_as_read(self):
        """Отметить как прочитанное"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
