"""
Модели контента

AIGeneratedArticle - Статьи, сгенерированные AI
AuthorStyleProfile - Профиль стиля написания автора
ArticleGenerationMetric - Метрики производительности генерации
"""
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class AIGeneratedArticle(models.Model):
    """Статьи, сгенерированные AI-ассистентом"""
    
    schedule = models.ForeignKey('schedule.AISchedule', on_delete=models.SET_NULL, null=True, blank=True, related_name='generated_articles', verbose_name="Расписание")
    article = models.ForeignKey('blog.Post', on_delete=models.CASCADE, related_name='ai_generation_info', verbose_name="Статья")
    source_urls = models.TextField(blank=True, verbose_name="Источники")
    prompt = models.TextField(blank=True, verbose_name="Промпт")
    ai_response = models.TextField(blank=True, verbose_name="Ответ AI")
    generation_time_seconds = models.IntegerField(default=0, verbose_name="Время генерации (сек)")
    api_calls_count = models.IntegerField(default=0, verbose_name="Количество API вызовов")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата генерации")
    
    class Meta:
        verbose_name = "AI-статья"
        verbose_name_plural = "AI-статьи"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"AI: {self.article.title}"


class AuthorStyleProfile(models.Model):
    """Профиль стиля написания автора для имитации AI"""
    
    profile = models.OneToOneField(
        'Visitor.Profile',
        on_delete=models.CASCADE,
        related_name='style_profile',
        verbose_name="Профиль",
        null=True,
        blank=True,
    )
    style_name = models.CharField(max_length=200, blank=True, null=True, default='', verbose_name="Название стиля", help_text='Например: "Легкий и вдохновляющий", "Экспертный научный"')
    style_analysis = models.JSONField(default=dict, blank=True, null=True, verbose_name="Анализ стиля", help_text="Результат автоматического анализа статей автора")
    top_articles = models.ManyToManyField('blog.Post', blank=True, verbose_name="Лучшие статьи для обучения")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    usage_count = models.IntegerField(default=0, verbose_name="Использований")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")   
    
    def get_style_prompt(self):
        """Генерирует текст для промпта на основе анализа"""
        from Asistent.style_analyzer import StyleAnalyzer
        
        analyzer = StyleAnalyzer()
        return analyzer.generate_style_prompt(self.style_analysis)
    
    def update_analysis(self, limit=10):
        """Обновляет анализ стиля на основе последних статей"""
        from Asistent.style_analyzer import StyleAnalyzer
        import logging
        
        logger = logging.getLogger(__name__)
        analyzer = StyleAnalyzer()
        self.style_analysis = analyzer.analyze_author_style(self.author, limit=limit)
        self.save()
        
        logger.info(f"✅ Обновлен профиль стиля @{self.author.username}")


class ArticleGenerationMetric(models.Model):
    """Метрики производительности генерации статей"""
    
    template = models.ForeignKey(
        'Asistent.PromptTemplate',
        on_delete=models.CASCADE,
        related_name='generation_metrics',
        verbose_name='Шаблон промпта'
    )
    
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Начало генерации',
        db_index=True
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Завершение генерации'
    )
    
    total_duration = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Общее время (сек)',
        help_text='Время от начала до конца генерации'
    )
    success = models.BooleanField(
        default=False,
        verbose_name='Успешно',
        db_index=True
    )
    error_message = models.TextField(
        blank=True,
        verbose_name='Сообщение об ошибке'
    )
    
    # Метрики этапов (в секундах)
    context_build_duration = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Построение контекста (сек)'
    )
    content_generation_duration = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Генерация контента (сек)'
    )
    title_generation_duration = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Генерация заголовка (сек)'
    )
    image_processing_duration = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Обработка изображения (сек)'
    )
    tags_generation_duration = models.FloatField(
        null=True,
        blank=True,
        verbose_name='Генерация тегов (сек)'
    )
    
    # Метрики результата
    content_length = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Длина контента (символов)'
    )
    word_count = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Количество слов'
    )
    tags_count = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Количество тегов'
    )
    has_image = models.BooleanField(
        default=False,
        verbose_name='Есть изображение'
    )
    image_source_type = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Тип источника изображения'
    )
    
    gigachat_model = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Модель GigaChat'
    )
    user_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='ID пользователя'
    )
    
    class Meta:
        verbose_name = '📊 Метрика генерации статьи'
        verbose_name_plural = '📊 Метрики генерации статей'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['template', '-started_at']),
            models.Index(fields=['success', '-started_at']),
        ]
    
    def __str__(self):
        status = "✅" if self.success else "❌"
        duration = f"{self.total_duration:.1f}s" if self.total_duration else "N/A"
        return f"{status} {self.template.name} - {duration} ({self.started_at.strftime('%d.%m %H:%M')})"
    
    def complete(self, success: bool = True, error_message: str = ''):
        """Завершение метрики с расчётом общего времени"""
        from django.utils import timezone
        self.completed_at = timezone.now()
        self.success = success
        self.error_message = error_message
        
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.total_duration = delta.total_seconds()
        
        self.save()
