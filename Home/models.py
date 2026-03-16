from django.db import models
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
import json
import os
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


def validate_image_size(file):
    """Валидатор размера изображения (макс 2MB)"""
    limit_mb = 2
    if file.size > limit_mb * 1024 * 1024:
        raise ValidationError(f'Размер файла не должен превышать {limit_mb}MB. Текущий размер: {file.size / (1024*1024):.1f}MB')


def validate_video_size(file):
    """Валидатор размера видео (макс 10MB)"""
    limit_mb = 10
    if file.size > limit_mb * 1024 * 1024:
        raise ValidationError(f'Размер видео не должен превышать {limit_mb}MB. Текущий размер: {file.size / (1024*1024):.1f}MB')


class LandingTheme(models.Model):
    """Модель для хранения тем оформления лендинга"""
    
    name = models.CharField(
        'Название темы',
        max_length=200,
        help_text='Например: "Лето 2025", "Мода и стиль", "Минимализм"'
    )
    
    style_prompt = models.TextField(
        'Стиль/Запрос для AI',
        help_text='Описание стиля, который использовался для генерации (например: "яркие летние цвета, пляж, солнце")'
    )
    
    is_active = models.BooleanField(
        'Активная тема',
        default=False,
        help_text='Тема, которая сейчас применена к лендингу'
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name='Создал',
        related_name='created_themes'
    )
    
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    
    # Сохраненная конфигурация секций (JSON)
    sections_config = models.JSONField(
        'Конфигурация секций',
        default=dict,
        help_text='JSON с настройками всех секций лендинга'
    )
    
    preview_image = models.ImageField(
        'Превью темы',
        upload_to='landing/themes/previews/',
        blank=True,
        null=True,
        help_text='Скриншот или превью темы'
    )
    
    class Meta:
        verbose_name = 'Тема лендинга'
        verbose_name_plural = 'Темы лендинга'
        ordering = ['-created_at']
    
    def __str__(self):
        status = '✅ Активна' if self.is_active else ''
        return f"{self.name} {status}".strip()
    
    def save(self, *args, **kwargs):
        # Если эта тема активируется, деактивируем остальные
        if self.is_active:
            LandingTheme.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)
    
    def apply_theme(self):
        """Применяет тему к лендингу (восстанавливает секции из сохраненной конфигурации)"""
        if not self.sections_config:
            return False
        
        # Восстанавливаем секции из JSON
        for section_key, config in self.sections_config.items():
            section, created = LandingSection.objects.get_or_create(section=section_key)
            
            # Обновляем поля секции
            for field, value in config.items():
                if hasattr(section, field):
                    setattr(section, field, value)
            
            section.save()
        
        # Делаем эту тему активной
        self.is_active = True
        self.save()
        
        return True
    
    @classmethod
    def create_from_current(cls, name, style_prompt, user=None):
        """Создает новую тему на основе текущих настроек лендинга"""
        # Собираем конфигурацию всех активных секций
        sections_config = {}
        for section in LandingSection.objects.filter(is_active=True):
            sections_config[section.section] = {
                'media_type': section.media_type,
                'background_image': section.background_image.name if section.background_image else None,
                'background_video': section.background_video.name if section.background_video else None,
                'video_url': section.video_url,
                'gradient_colors': section.gradient_colors,
                'opacity': section.opacity,
                'overlay_color': section.overlay_color,
                'overlay_opacity': section.overlay_opacity,
                'is_active': section.is_active,
                'ai_generated': section.ai_generated,
                'ai_search_query': section.ai_search_query,
            }
        
        # Создаем новую тему
        theme = cls.objects.create(
            name=name,
            style_prompt=style_prompt,
            is_active=False,
            created_by=user,
            sections_config=sections_config
        )
        
        return theme


class LandingSection(models.Model):
    """Модель для управления фонами секций лендинга"""
    
    SECTION_CHOICES = [
        ('hero', '🎯 Hero секция'),
        ('features', '💎 Уникальность контента + AI Технологии (объединённая)'),
        ('categories', '🔥 Популярные категории'),
        ('blogger', '✍️ Станьте блогером'),
        ('advertising', '💣 Реклама'),
        ('top_posts', '🏆 Лучшие статьи'),
        ('network', '🌐 Сеть порталов'),
        ('cta', '🎯 Call to Action'),
    ]
    
    MEDIA_TYPE_CHOICES = [
        ('none', 'Без фона'),
        ('image', 'Изображение'),
        ('video', 'Видео'),
        ('gradient', 'Градиент'),
    ]
    
    section = models.CharField(
        'Секция',
        max_length=50,
        choices=SECTION_CHOICES,
        unique=True,
        help_text='Выберите секцию лендинга'
    )
    
    media_type = models.CharField(
        'Тип медиа',
        max_length=20,
        choices=MEDIA_TYPE_CHOICES,
        default='gradient'
    )
    
    background_image = models.ImageField(
        'Фоновое изображение',
        upload_to='landing/backgrounds/',
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp', 'gif']),
            validate_image_size
        ],
        help_text='Рекомендуемый размер: 1920x1080px, макс 2MB (автоматически оптимизируется)'
    )
    
    background_video = models.FileField(
        'Фоновое видео',
        upload_to='landing/videos/',
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(['mp4', 'webm', 'ogg']),
            validate_video_size
        ],
        help_text='Рекомендуемый формат: MP4, макс 10MB (используйте сжатие!)'
    )
    
    video_url = models.URLField(
        'URL видео (embed)',
        blank=True,
        null=True,
        help_text='Ссылка на embed видео с Rutube, VK, YouTube и т.д.'
    )
    
    gradient_colors = models.CharField(
        'Цвета градиента',
        max_length=200,
        blank=True,
        default='from-pink-500 via-purple-500 to-indigo-600',
        help_text='Tailwind CSS классы градиента, например: from-blue-500 to-purple-600'
    )
    
    opacity = models.IntegerField(
        'Прозрачность фона (%)',
        default=90,
        help_text='От 0 до 100'
    )
    
    overlay_color = models.CharField(
        'Цвет наложения',
        max_length=50,
        blank=True,
        default='black',
        help_text='Цвет затемнения/осветления поверх фона'
    )
    
    overlay_opacity = models.IntegerField(
        'Прозрачность наложения (%)',
        default=0,
        help_text='От 0 до 100'
    )
    
    is_active = models.BooleanField(
        'Активно',
        default=True,
        help_text='Использовать этот фон для секции'
    )
    
    ai_generated = models.BooleanField(
        'Создано AI',
        default=False,
        help_text='Медиафайл подобран автоматически AI-ассистентом'
    )
    
    ai_search_query = models.CharField(
        'Запрос для AI',
        max_length=200,
        blank=True,
        help_text='Поисковый запрос, использованный AI для подбора контента'
    )
    
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)
    
    class Meta:
        verbose_name = 'Секция лендинга'
        verbose_name_plural = 'Секции лендинга'
        ordering = ['section']
    
    def __str__(self):
        return f"{self.get_section_display()} - {self.get_media_type_display()}"
    
    def save(self, *args, **kwargs):
        """Оптимизирует изображение перед сохранением"""
        if self.background_image and hasattr(self.background_image, 'file'):
            try:
                from .image_optimizer import ImageOptimizer
                
                # Определяем тип секции для оптимизации
                section_type = 'hero' if self.section == 'hero' else 'section'
                
                # Оптимизируем изображение
                optimized, extension = ImageOptimizer.optimize_image(
                    self.background_image.file,
                    max_size=section_type,
                    format='webp'
                )
                
                if optimized:
                    # Генерируем новое имя файла
                    original_name = os.path.splitext(self.background_image.name)[0]
                    new_name = f"{original_name}_optimized.{extension}"
                    
                    # Заменяем файл оптимизированным
                    self.background_image.save(new_name, optimized, save=False)
                    logger.info(f"Optimized image for section {self.section}")
                    
            except Exception as e:
                logger.warning(f"Could not optimize image for {self.section}: {e}")
                # Продолжаем сохранение без оптимизации
        
        super().save(*args, **kwargs)
    
    def get_background_style(self):
        """Возвращает CSS/HTML код для фона секции"""
        if not self.is_active:
            return {}
        
        style = {
            'type': self.media_type,
            'classes': '',
            'inline_style': '',
            'video_url': None,
        }
        
        if self.media_type == 'image' and self.background_image:
            style['inline_style'] = f"background-image: url('{self.background_image.url}'); background-size: cover; background-position: center;"
            if self.overlay_opacity > 0:
                style['overlay'] = f"background-color: rgba(0,0,0,{self.overlay_opacity/100});"
        
        elif self.media_type == 'video':
            if self.background_video:
                style['video_url'] = self.background_video.url
            elif self.video_url:
                style['video_url'] = self.video_url
        
        elif self.media_type == 'gradient':
            style['classes'] = f"bg-gradient-to-br {self.gradient_colors}"
            if self.opacity < 100:
                style['classes'] += f" opacity-{self.opacity}"
        
        return style


class LandingConfig(models.Model):
    """Singleton модель для управления активным лендингом"""
    
    LANDING_CHOICES = [
        ('landing1', '🎨 Лендинг №1 (Оригинальный IdealImage)'),
        ('landing2', '💅 Лендинг №2 (Салон красоты)'),
    ]
    
    active_landing = models.CharField(
        'Активный лендинг',
        max_length=20,
        choices=LANDING_CHOICES,
        default='landing1',
        help_text='Выберите лендинг, который будет отображаться на главной странице'
    )
    
    updated_at = models.DateTimeField('Обновлено', auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Изменил'
    )
    
    class Meta:
        verbose_name = 'Настройка главной страницы'
        verbose_name_plural = 'Настройки главной страницы'
    
    def __str__(self):
        return f"Активный лендинг: {self.get_active_landing_display()}"
    
    def save(self, *args, **kwargs):
        # Singleton: всегда сохраняем только одну запись с ID=1
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_solo(cls):
        """Получить единственную запись конфигурации"""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class Portal(models.Model):
    """Модель для карточек порталов в секции 'Сеть порталов'"""
    
    name = models.CharField(
        'Название портала',
        max_length=100,
        help_text='Например: "IdealImage.ru", "BeautyStyle.ru"'
    )
    
    description = models.CharField(
        'Описание',
        max_length=200,
        help_text='Краткое описание портала'
    )
    
    image = models.ImageField(
        'Изображение портала',
        upload_to='landing/portals/',
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp']),
            validate_image_size
        ],
        help_text='Рекомендуемый размер: 400x300px, макс 2MB'
    )
    
    url = models.URLField(
        'Ссылка на портал',
        help_text='Полный URL портала (например: https://idealimage.ru)'
    )
    
    is_main = models.BooleanField(
        'Главный портал',
        default=False,
        help_text='Выделить как главный портал (специальная рамка)'
    )
    
    is_active = models.BooleanField(
        'Активен',
        default=True,
        help_text='Показывать на лендинге'
    )
    
    order = models.IntegerField(
        'Порядок сортировки',
        default=0,
        help_text='Чем меньше число, тем выше в списке'
    )
    
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)
    
    class Meta:
        verbose_name = 'Портал'
        verbose_name_plural = '🌐 Порталы (Сеть)'
        ordering = ['order', 'name']
    
    def __str__(self):
        status = '⭐ Главный' if self.is_main else ''
        active = '✅' if self.is_active else '❌'
        return f"{active} {self.name} {status}".strip()
    
    def get_icon(self):
        """Возвращает эмодзи иконку в зависимости от названия портала"""
        name_lower = self.name.lower()
        
        if 'ideal' in name_lower or 'главн' in name_lower:
            return '👑'
        elif 'beauty' in name_lower or 'красот' in name_lower:
            return '💄'
        elif 'fashion' in name_lower or 'мод' in name_lower:
            return '👗'
        elif 'health' in name_lower or 'здоров' in name_lower:
            return '💪'
        elif 'makeup' in name_lower or 'мейк' in name_lower:
            return '💋'
        elif 'hair' in name_lower or 'волос' in name_lower:
            return '💇'
        elif 'skin' in name_lower or 'кож' in name_lower:
            return '✨'
        elif 'nail' in name_lower or 'ногт' in name_lower:
            return '💅'
        else:
            return '🌐'
    
    def save(self, *args, **kwargs):
        """Оптимизирует изображение перед сохранением"""
        if self.image and hasattr(self.image, 'file'):
            try:
                from .image_optimizer import ImageOptimizer
                
                # Оптимизируем изображение (уменьшаем размер и качество для сверхбыстрой загрузки)
                optimized, extension = ImageOptimizer.optimize_image(
                    self.image.file,
                    max_size=(320, 240),
                    format='webp'
                )
                if optimized:
                    # Генерируем только имя файла (без пути), так как Django сам добавит подпапку из upload_to
                    original_filename = os.path.basename(self.image.name)
                    name_base = os.path.splitext(original_filename)[0]
                    new_name = f"{name_base}_portal.{extension}"
                    
                    # Заменяем файл оптимизированным
                    self.image.save(new_name, optimized, save=False)
                    logger.info(f"Optimized portal image: {self.name}")
                    
            except Exception as e:
                logger.warning(f"Could not optimize portal image for {self.name}: {e}")
        
        super().save(*args, **kwargs)
