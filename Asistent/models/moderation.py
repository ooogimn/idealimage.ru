"""
Модели для ботов-модераторов

BotProfile - Профили ботов для автоматического комментирования
BotActivity - Лог активности ботов
"""
from django.db import models
from django.contrib.auth.models import User


class BotProfile(models.Model):
    """Профили ботов для автоматического комментирования и лайков"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='bot_profile',
        verbose_name='Пользователь'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активен'
    )
    
    bot_name = models.CharField(
        max_length=100,
        verbose_name='Имя бота',
        help_text='Отображаемое имя для комментариев'
    )
    
    comment_style = models.CharField(
        max_length=50,
        choices=[
            ('formal', 'Формальный'),
            ('casual', 'Неформальный'),
            ('friendly', 'Дружелюбный'),
            ('expert', 'Экспертный'),
            ('humorous', 'Юмористический'),
        ],
        default='friendly',
        verbose_name='Стиль комментирования'
    )
    
    comment_templates = models.JSONField(
        default=list,
        verbose_name='Шаблоны комментариев',
        help_text='Список шаблонов для генерации комментариев'
    )
    
    max_comments_per_day = models.IntegerField(
        default=10,
        verbose_name='Максимум комментариев в день'
    )
    
    max_likes_per_day = models.IntegerField(
        default=20,
        verbose_name='Максимум лайков в день'
    )
    
    preferred_categories = models.JSONField(
        default=list,
        verbose_name='Предпочитаемые категории',
        help_text='Категории статей для комментирования'
    )
    
    avoid_categories = models.JSONField(
        default=list,
        verbose_name='Избегаемые категории',
        help_text='Категории статей, которые бот не комментирует'
    )
    
    min_article_views = models.IntegerField(
        default=100,
        verbose_name='Минимальные просмотры статьи',
        help_text='Комментировать только статьи с таким количеством просмотров'
    )
    
    comment_probability = models.FloatField(
        default=0.3,
        verbose_name='Вероятность комментирования',
        help_text='От 0.0 до 1.0'
    )
    
    like_probability = models.FloatField(
        default=0.5,
        verbose_name='Вероятность лайка',
        help_text='От 0.0 до 1.0'
    )
    
    last_activity = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Последняя активность'
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата создания'
    )
    
    class Meta:
        verbose_name = 'Профиль бота'
        verbose_name_plural = 'Профили ботов'
    
    def __str__(self):
        return f"{self.bot_name} ({self.user.username})"
    
    def can_comment_today(self):
        """Можно ли комментировать сегодня"""
        from django.utils import timezone
        
        today = timezone.now().date()
        today_comments = self.user.comments.filter(
            created_at__date=today
        ).count()
        
        return today_comments < self.max_comments_per_day
    
    def can_like_today(self):
        """Можно ли лайкать сегодня"""
        from django.utils import timezone
        from blog.models import PostLike
        
        today = timezone.now().date()
        today_likes = PostLike.objects.filter(
            user=self.user,
            created_at__date=today
        ).count()
        
        return today_likes < self.max_likes_per_day
    
    def get_random_comment_template(self):
        """Получить случайный шаблон комментария"""
        import random
        
        if not self.comment_templates:
            return "Интересная статья!"
        
        return random.choice(self.comment_templates)


class BotActivity(models.Model):
    """Лог активности ботов"""
    
    ACTION_CHOICES = [
        ('comment', 'Комментарий'),
        ('like', 'Лайк'),
        ('skip', 'Пропуск'),
    ]
    
    bot_profile = models.ForeignKey(
        BotProfile,
        on_delete=models.CASCADE,
        related_name='activities',
        verbose_name='Профиль бота'
    )
    
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name='Действие'
    )
    
    article = models.ForeignKey(
        'blog.Post',
        on_delete=models.CASCADE,
        related_name='bot_activities',
        verbose_name='Статья'
    )
    
    content = models.TextField(
        blank=True,
        verbose_name='Содержание',
        help_text='Текст комментария или причина пропуска'
    )
    
    success = models.BooleanField(
        default=True,
        verbose_name='Успешно'
    )
    
    error_message = models.TextField(
        blank=True,
        verbose_name='Сообщение об ошибке'
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Дата действия'
    )
    
    class Meta:
        verbose_name = 'Активность бота'
        verbose_name_plural = 'Активности ботов'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.bot_profile.bot_name} - {self.get_action_display()} - {self.article.title[:50]}"
