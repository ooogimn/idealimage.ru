from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
import uuid


class Donation(models.Model):
    """Модель для хранения информации о донатах"""
    
    PAYMENT_METHOD_CHOICES = [
        ('yandex', 'Яндекс.Касса'),
        ('sberpay', 'СберПей'),
        ('sbp', 'Система Быстрых Платежей'),
        ('qr', 'QR-код'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Ожидание оплаты'),
        ('processing', 'В обработке'),
        ('succeeded', 'Успешно'),
        ('canceled', 'Отменено'),
        ('refunded', 'Возврат'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Пользователь')
    user_email = models.EmailField(verbose_name='Email донатера', help_text='Для отправки благодарственного письма')
    user_name = models.CharField(max_length=255, verbose_name='Имя донатера', blank=True)
    
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Сумма')
    currency = models.CharField(max_length=3, default='RUB', verbose_name='Валюта')
    
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, verbose_name='Способ оплаты')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name='Статус')
    
    payment_id = models.CharField(max_length=255, blank=True, null=True, verbose_name='ID платежа в платежной системе')
    payment_url = models.URLField(blank=True, null=True, verbose_name='Ссылка на оплату')
    
    message = models.TextField(blank=True, verbose_name='Сообщение от донатера', help_text='Пожелания или комментарий')
    is_anonymous = models.BooleanField(default=False, verbose_name='Анонимный донат')
    
    qr_code = models.TextField(blank=True, null=True, verbose_name='Base64 QR-код')
    
    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата завершения')
    
    # Дополнительные данные от платежной системы
    payment_data = models.JSONField(default=dict, blank=True, verbose_name='Данные платежа')
    
    # Новые поля для монетизации
    PAYMENT_PURPOSE_CHOICES = [
        ('donation', 'Донат'),
        ('premium_monthly', 'Premium подписка (месяц)'),
        ('premium_3months', 'Premium подписка (3 месяца)'),
        ('premium_yearly', 'Premium подписка (год)'),
        ('ai_coauthor_monthly', 'AI-Соавтор (месяц)'),
        ('ai_once', 'AI-Соавтор (разово)'),
        ('ai_pack_5', 'AI-Соавтор (пакет 5 статей)'),
        ('ai_pack_10', 'AI-Соавтор (пакет 10 статей)'),
        ('ai_pack_30', 'AI-Соавтор (пакет 30 статей)'),
        ('marathon_skin', 'Марафон: Идеальная кожа'),
        ('marathon_makeup', 'Марафон: Макияж'),
        ('marathon_wardrobe', 'Марафон: Капсульный гардероб'),
        ('ad_main_banner', 'Реклама: Баннер на главной'),
        ('ad_sidebar', 'Реклама: Боковой блок'),
        ('ad_in_content', 'Реклама: Внутри статей'),
        ('ad_article', 'Реклама: Рекламная статья'),
        ('ad_ticker', 'Реклама: Бегущая строка'),
        ('ad_telegram', 'Реклама: Посты в Telegram'),
        ('ad_pack_start', 'Реклама: Пакет Старт'),
        ('ad_pack_pro', 'Реклама: Пакет Профи'),
    ]
    
    payment_purpose = models.CharField(
        max_length=30, 
        choices=PAYMENT_PURPOSE_CHOICES, 
        default='donation',
        verbose_name='Назначение платежа'
    )
    
    # Связь со статьей и автором (для распределения бонусов)
    article = models.ForeignKey(
        'blog.Post',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='donations',
        verbose_name='Статья',
        help_text='Статья, через которую сделан донат'
    )
    article_author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_donations',
        verbose_name='Автор статьи',
        help_text='Автор статьи (копируется из статьи при создании доната)'
    )
    
    class Meta:
        verbose_name = 'Донат'
        verbose_name_plural = 'Донаты'
        ordering = ['-created_at']
    
    def get_donor_name(self):
        """Возвращает имя донатера или 'Анонимный'"""
        if self.is_anonymous:
            return 'Анонимный донатер'
        return self.user_name or (self.user.get_full_name() if self.user else 'Гость')


class Subscription(models.Model):
    """Модель для подписок пользователей"""
    
    SUBSCRIPTION_TYPE_CHOICES = [
        ('premium', 'Premium (без рекламы)'),
        ('ai_coauthor', 'AI-Соавтор'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='Пользователь')
    subscription_type = models.CharField(
        max_length=20, 
        choices=SUBSCRIPTION_TYPE_CHOICES,
        verbose_name='Тип подписки'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    start_date = models.DateTimeField(auto_now_add=True, verbose_name='Дата начала')
    end_date = models.DateTimeField(verbose_name='Дата окончания')
    is_active = models.BooleanField(default=True, verbose_name='Активна')
    
    # Связь с платежом
    payment = models.ForeignKey(
        Donation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='Платеж'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    def __str__(self):
        return f"{self.user.username} - {self.get_subscription_type_display()}"
    
    class Meta:
        verbose_name = 'Подписка'
        verbose_name_plural = 'Подписки'
        ordering = ['-created_at']


class PaidArticle(models.Model):
    """Модель для платных статей"""
    
    article = models.OneToOneField(
        'blog.Post', 
        on_delete=models.CASCADE, 
        related_name='paid_access',
        verbose_name='Статья'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    is_active = models.BooleanField(default=True, verbose_name='Активна')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    
    def __str__(self):
        return f"Платная статья: {self.article.title} - {self.price}₽"
    
    class Meta:
        verbose_name = 'Платная статья'
        verbose_name_plural = 'Платные статьи'
        ordering = ['-created_at']


class ArticlePurchase(models.Model):
    """Модель для покупок платных статей"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='Пользователь')
    article = models.ForeignKey(PaidArticle, on_delete=models.CASCADE, verbose_name='Статья')
    payment = models.ForeignKey(
        Donation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='Платеж'
    )
    purchased_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата покупки')
    
    def __str__(self):
        return f"{self.user.username} купил {self.article.article.title}"
    
    class Meta:
        verbose_name = 'Покупка статьи'
        verbose_name_plural = 'Покупки статей'
        unique_together = ['user', 'article']
        ordering = ['-purchased_at']


class Marathon(models.Model):
    """Модель для марафонов"""
    
    title = models.CharField(max_length=200, verbose_name='Название')
    description = models.TextField(verbose_name='Описание')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    duration_days = models.IntegerField(verbose_name='Длительность (дней)')
    is_active = models.BooleanField(default=True, verbose_name='Активен')
    
    # Связь со статьями марафона
    articles = models.ManyToManyField(
        'blog.Post', 
        blank=True,
        verbose_name='Статьи марафона'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    def __str__(self):
        return f"Марафон: {self.title} - {self.price}₽"
    
    class Meta:
        verbose_name = 'Марафон'
        verbose_name_plural = 'Марафоны'
        ordering = ['-created_at']


class MarathonPurchase(models.Model):
    """Модель для покупок марафонов"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='Пользователь')
    marathon = models.ForeignKey(Marathon, on_delete=models.CASCADE, verbose_name='Марафон')
    payment = models.ForeignKey(
        Donation, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name='Платеж'
    )
    purchased_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата покупки')
    
    def __str__(self):
        return f"{self.user.username} купил {self.marathon.title}"
    
    class Meta:
        verbose_name = 'Покупка марафона'
        verbose_name_plural = 'Покупки марафонов'
        unique_together = ['user', 'marathon']
        ordering = ['-purchased_at']


class DonationNotification(models.Model):
    """Модель для отслеживания отправленных уведомлений"""
    
    NOTIFICATION_TYPES = [
        ('email_donor', 'Email донатеру'),
        ('email_admin', 'Email администратору'),
        ('telegram', 'Telegram уведомление'),
    ]
    
    donation = models.ForeignKey(Donation, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    recipient = models.CharField(max_length=255, verbose_name='Получатель')
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name='Отправлено')
    is_successful = models.BooleanField(default=True, verbose_name='Успешно')
    error_message = models.TextField(blank=True, verbose_name='Сообщение об ошибке')
    
    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-sent_at']
    
    def __str__(self):
        return f'{self.get_notification_type_display()} для доната {self.donation.id}'


class PaymentWebhookLog(models.Model):
    """Логирование входящих webhook от платежных систем"""
    
    payment_system = models.CharField(max_length=50, verbose_name='Платежная система')
    webhook_data = models.JSONField(verbose_name='Данные webhook')
    donation = models.ForeignKey(Donation, on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_logs')
    
    processed = models.BooleanField(default=False, verbose_name='Обработан')
    error = models.TextField(blank=True, verbose_name='Ошибка обработки')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата получения')
    
    class Meta:
        verbose_name = 'Webhook лог'
        verbose_name_plural = 'Webhook логи'
        ordering = ['-created_at']
    
    def __str__(self):
        return f'Webhook от {self.payment_system} - {self.created_at}'


class WebhookEvent(models.Model):
    """
    Идемпотентный реестр webhook событий.
    Защищает от повторной обработки одного и того же event_id.
    """

    provider = models.CharField(max_length=50, verbose_name='Провайдер')
    event_id = models.CharField(max_length=255, verbose_name='ID события')
    payload_hash = models.CharField(max_length=64, verbose_name='SHA256 payload')
    donation = models.ForeignKey(
        Donation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='webhook_events',
        verbose_name='Связанный донат'
    )
    processed = models.BooleanField(default=False, verbose_name='Обработано')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name='Обработано в')

    class Meta:
        verbose_name = 'Webhook событие'
        verbose_name_plural = 'Webhook события'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'event_id'],
                name='uq_webhook_provider_event'
            )
        ]
        indexes = [
            models.Index(fields=['provider', 'event_id']),
            models.Index(fields=['processed', '-created_at']),
        ]

    def __str__(self):
        return f'{self.provider}:{self.event_id}'


class DonationSettings(models.Model):
    """Настройки системы донатов"""
    
    # Минимальная и максимальная суммы
    min_amount = models.DecimalField(max_digits=10, decimal_places=2, default=100, verbose_name='Минимальная сумма')
    max_amount = models.DecimalField(max_digits=10, decimal_places=2, default=100000, verbose_name='Максимальная сумма')
    
    # Предустановленные суммы для быстрого выбора
    preset_amounts = models.JSONField(
        default=list,
        verbose_name='Предустановленные суммы',
        help_text='Например: [100, 500, 1000, 5000]'
    )
    
    # Включить/выключить платежные методы
    enable_yandex = models.BooleanField(default=True, verbose_name='Включить Яндекс.Кассу')
    enable_sberpay = models.BooleanField(default=True, verbose_name='Включить СберПей')
    enable_sbp = models.BooleanField(default=True, verbose_name='Включить СБП')
    enable_qr = models.BooleanField(default=True, verbose_name='Включить QR-код')
    
    # Настройки уведомлений
    send_email_to_donor = models.BooleanField(default=True, verbose_name='Отправлять email донатеру')
    send_email_to_admin = models.BooleanField(default=True, verbose_name='Отправлять email администратору')
    admin_emails = models.TextField(
        verbose_name='Email администраторов',
        help_text='По одному на строку',
        blank=True
    )
    
    # Тексты для писем
    thank_you_subject = models.CharField(
        max_length=255,
        default='Спасибо за ваш донат!',
        verbose_name='Тема благодарственного письма'
    )
    thank_you_message = models.TextField(
        default='Большое спасибо за вашу поддержку! Ваш донат помогает нам развиваться.',
        verbose_name='Текст благодарственного письма'
    )
    
    # Настройки отображения
    donation_page_title = models.CharField(
        max_length=255,
        default='Поддержать проект',
        verbose_name='Заголовок страницы донатов'
    )
    donation_page_description = models.TextField(
        default='Ваша поддержка помогает нам развивать проект и создавать качественный контент.',
        verbose_name='Описание на странице донатов'
    )
    
    class Meta:
        verbose_name = 'Настройки донатов'
        verbose_name_plural = 'Настройки донатов'
    
    def __str__(self):
        return 'Настройки системы донатов'
    
    def save(self, *args, **kwargs):
        # Гарантируем, что будет только одна запись настроек
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_settings(cls):
        """Получить настройки (синглтон)"""
        obj, created = cls.objects.get_or_create(pk=1)
        if created:
            obj.preset_amounts = [100, 500, 1000, 5000]
            obj.save()
        return obj


# ============================================
# Модели системы бонусов для авторов
# ============================================

class AuthorRole(models.Model):
    """Роли авторов с условиями и настройками бонусов"""
    
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Название роли',
        help_text='Стажёр, Автор, Писатель, Бестселлер'
    )
    
    level = models.IntegerField(
        unique=True,
        verbose_name='Уровень роли',
        help_text='1-4, где 1 - самый низкий'
    )
    
    bonus_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name='Процент от донатов',
        help_text='Процент от донатов за статьи автора (по умолчанию)'
    )
    
    point_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1.0,
        verbose_name='Стоимость балла',
        help_text='Сколько рублей стоит один балл для этой роли'
    )
    
    description = models.TextField(
        blank=True,
        verbose_name='Описание роли'
    )
    
    color = models.CharField(
        max_length=7,
        default='#6B7280',
        verbose_name='Цвет',
        help_text='Цвет для отображения роли (HEX)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    class Meta:
        verbose_name = '💰 Бонусы: Роль автора'
        verbose_name_plural = '💰 Бонусы: Роли авторов'
        ordering = ['level']
    
    def __str__(self):
        return f'{self.name} (уровень {self.level})'


class BonusFormula(models.Model):
    """Формулы расчета баллов и условия получения роли"""
    
    role = models.OneToOneField(
        AuthorRole,
        on_delete=models.CASCADE,
        related_name='formula',
        verbose_name='Роль'
    )
    
    # Веса для расчета баллов
    articles_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=10.0,
        verbose_name='Вес статьи',
        help_text='Сколько баллов за одну опубликованную статью'
    )
    
    likes_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.5,
        verbose_name='Вес лайка',
        help_text='Сколько баллов за один лайк'
    )
    
    comments_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1.0,
        verbose_name='Вес комментария',
        help_text='Сколько баллов за один комментарий'
    )
    
    views_weight = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0.01,
        verbose_name='Вес просмотра',
        help_text='Сколько баллов за один просмотр'
    )
    
    tasks_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=5.0,
        verbose_name='Вес выполненного задания',
        help_text='Сколько баллов за одно выполненное задание'
    )
    
    # Минимальные требования для получения роли
    min_points_required = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Минимум баллов',
        help_text='Минимум баллов за неделю для получения этой роли'
    )
    
    min_articles_required = models.IntegerField(
        default=0,
        verbose_name='Минимум статей',
        help_text='Минимум статей за неделю (опционально)'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активна',
        help_text='Используется ли эта формула'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    class Meta:
        verbose_name = '💰 Бонусы: Формула расчета'
        verbose_name_plural = '💰 Бонусы: Формулы расчета'
    
    def __str__(self):
        return f'Формула для роли {self.role.name}'
    
    def calculate_points(self, articles, likes, comments, views, tasks):
        """Рассчитать баллы на основе активности"""
        points = (
            articles * float(self.articles_weight) +
            likes * float(self.likes_weight) +
            comments * float(self.comments_weight) +
            views * float(self.views_weight) +
            tasks * float(self.tasks_weight)
        )
        return round(points, 2)


class AuthorStats(models.Model):
    """Статистика активности автора за период"""
    
    PERIOD_TYPE_CHOICES = [
        ('week', 'Неделя'),
        ('month', 'Месяц'),
        ('all_time', 'Всё время'),
    ]
    
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='author_stats',
        verbose_name='Автор'
    )
    
    period_type = models.CharField(
        max_length=20,
        choices=PERIOD_TYPE_CHOICES,
        verbose_name='Тип периода'
    )
    
    period_start = models.DateTimeField(verbose_name='Начало периода')
    period_end = models.DateTimeField(verbose_name='Конец периода')
    
    # Статистика по статьям
    articles_count = models.IntegerField(default=0, verbose_name='Количество статей')
    total_likes = models.IntegerField(default=0, verbose_name='Всего лайков')
    total_comments = models.IntegerField(default=0, verbose_name='Всего комментариев')
    total_views = models.IntegerField(default=0, verbose_name='Всего просмотров')
    
    # Статистика по заданиям
    completed_tasks_count = models.IntegerField(default=0, verbose_name='Выполнено заданий')
    tasks_reward_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Вознаграждение за задания'
    )
    
    # Рассчитанные баллы и роль
    calculated_points = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Рассчитанные баллы'
    )
    
    current_role = models.ForeignKey(
        AuthorRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='author_stats',
        verbose_name='Текущая роль'
    )
    
    # Детальная информация (JSON)
    articles_detail = models.JSONField(
        default=list,
        verbose_name='Детали по статьям',
        help_text='Список статей с лайками, комментариями, просмотрами'
    )
    
    tasks_detail = models.JSONField(
        default=list,
        verbose_name='Детали по заданиям',
        help_text='Список выполненных заданий с вознаграждениями'
    )
    
    calculated_at = models.DateTimeField(auto_now=True, verbose_name='Дата расчета')
    
    class Meta:
        verbose_name = '💰 Бонусы: Статистика автора'
        verbose_name_plural = '💰 Бонусы: Статистика авторов'
        ordering = ['-period_start', 'author']
        unique_together = ['author', 'period_type', 'period_start']
        indexes = [
            models.Index(fields=['author', '-period_start']),
            models.Index(fields=['period_type', '-period_start']),
        ]
    
    def __str__(self):
        return f'{self.author.username} - {self.get_period_type_display()} ({self.period_start.date()})'


class AuthorBonus(models.Model):
    """Начисленные бонусы автору за период"""
    
    STATUS_CHOICES = [
        ('pending', 'Ожидает утверждения'),
        ('approved', 'Утверждено'),
        ('paid', 'Выплачено'),
        ('cancelled', 'Отменено'),
    ]
    
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bonuses',
        verbose_name='Автор'
    )
    
    period_start = models.DateTimeField(verbose_name='Начало периода')
    period_end = models.DateTimeField(verbose_name='Конец периода')
    
    # Бонус от донатов
    donations_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Сумма донатов',
        help_text='Сумма донатов за статьи автора'
    )
    
    bonus_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name='Процент бонуса'
    )
    
    calculated_bonus = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Бонус от донатов',
        help_text='Рассчитанный бонус в рублях из донатов'
    )
    
    # Вознаграждение за задания
    tasks_reward = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Вознаграждение за задания'
    )
    
    # Бонус от баллов
    points_earned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Заработанные баллы'
    )
    
    point_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1.0,
        verbose_name='Стоимость балла'
    )
    
    bonus_from_points = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Бонус из баллов'
    )
    
    # Итоговая сумма
    total_bonus = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Общий бонус',
        help_text='donations + tasks + points'
    )
    
    # Статус и метаданные
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Статус'
    )
    
    role_at_calculation = models.ForeignKey(
        AuthorRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Роль при расчете'
    )
    
    notes = models.TextField(blank=True, verbose_name='Примечания')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата утверждения')
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата выплаты')
    
    class Meta:
        verbose_name = '💰 Бонусы: Начисление'
        verbose_name_plural = '💰 Бонусы: Начисления'
        ordering = ['-period_start', 'author']
        indexes = [
            models.Index(fields=['author', '-period_start']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f'{self.author.username} - {self.total_bonus}₽ ({self.get_status_display()})'


class AuthorPenaltyReward(models.Model):
    """Штрафы и премии для авторов"""
    
    TYPE_CHOICES = [
        ('penalty', 'Штраф'),
        ('reward', 'Премия'),
    ]
    
    AMOUNT_TYPE_CHOICES = [
        ('fixed', 'Фиксированная сумма'),
        ('percentage', 'Процент от бонуса'),
    ]
    
    APPLIED_TO_CHOICES = [
        ('one_time', 'Разовый'),
        ('weekly', 'Еженедельный'),
        ('monthly', 'Ежемесячный'),
    ]
    
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='penalties_rewards',
        verbose_name='Автор'
    )
    
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        verbose_name='Тип'
    )
    
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Сумма',
        help_text='Сумма в рублях или процентах'
    )
    
    amount_type = models.CharField(
        max_length=20,
        choices=AMOUNT_TYPE_CHOICES,
        verbose_name='Тип суммы'
    )
    
    reason = models.TextField(verbose_name='Причина')
    
    applied_to = models.CharField(
        max_length=20,
        choices=APPLIED_TO_CHOICES,
        default='one_time',
        verbose_name='Применение'
    )
    
    applied_from = models.DateTimeField(verbose_name='Действует с')
    applied_until = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Действует до',
        help_text='Оставьте пустым для бессрочного'
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_penalties_rewards',
        verbose_name='Создал'
    )
    
    is_active = models.BooleanField(default=True, verbose_name='Активен')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    
    class Meta:
        verbose_name = '💰 Бонусы: Штраф/Премия'
        verbose_name_plural = '💰 Бонусы: Штрафы и премии'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['author', 'is_active']),
            models.Index(fields=['applied_from', 'applied_until']),
        ]
    
    def __str__(self):
        type_name = 'Штраф' if self.type == 'penalty' else 'Премия'
        return f'{type_name} для {self.author.username}: {self.amount}₽ - {self.reason[:50]}'
    
    def calculate_amount(self, base_amount):
        """Рассчитать фактическую сумму на основе базового бонуса"""
        if self.amount_type == 'fixed':
            return float(self.amount)
        else:  # percentage
            return float(base_amount) * float(self.amount) / 100


class WeeklyReport(models.Model):
    """Еженедельные отчеты по бонусам"""
    
    week_start = models.DateTimeField(verbose_name='Начало недели')
    week_end = models.DateTimeField(verbose_name='Конец недели')
    
    generated_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата генерации')
    
    # Агрегированные данные
    report_data = models.JSONField(
        default=dict,
        verbose_name='Данные отчета',
        help_text='JSON с данными всех авторов'
    )
    
    total_donations = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Общая сумма донатов'
    )
    
    total_bonuses = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Общая сумма бонусов'
    )
    
    total_tasks_rewards = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Общая сумма за задания'
    )
    
    authors_count = models.IntegerField(default=0, verbose_name='Количество авторов')
    
    # Статус отчета
    is_finalized = models.BooleanField(
        default=False,
        verbose_name='Зафиксирован',
        help_text='После фиксации отчет нельзя изменить'
    )
    
    finalized_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата фиксации'
    )
    
    finalized_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finalized_reports',
        verbose_name='Зафиксировал'
    )
    
    is_paid = models.BooleanField(default=False, verbose_name='Оплачен')
    
    notes = models.TextField(blank=True, verbose_name='Примечания')
    
    class Meta:
        verbose_name = '💰 Бонусы: Недельный отчет'
        verbose_name_plural = '💰 Бонусы: Недельные отчеты'
        ordering = ['-week_start']
        indexes = [
            models.Index(fields=['-week_start']),
            models.Index(fields=['is_finalized']),
        ]
    
    def __str__(self):
        return f'Отчет за {self.week_start.date()} - {self.week_end.date()}'


class BonusPaymentRegistry(models.Model):
    """Реестр выплат бонусов авторам"""
    
    STATUS_CHOICES = [
        ('pending', 'Ожидает оплаты'),
        ('paid', 'Оплачено'),
        ('partial', 'Частично оплачено'),
        ('cancelled', 'Отменено'),
    ]
    
    week_report = models.ForeignKey(
        WeeklyReport,
        on_delete=models.CASCADE,
        related_name='payment_registry',
        verbose_name='Недельный отчет'
    )
    
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payment_registry',
        verbose_name='Автор'
    )
    
    bonus = models.OneToOneField(
        AuthorBonus,
        on_delete=models.CASCADE,
        related_name='payment_record',
        verbose_name='Начисление бонуса'
    )
    
    amount_to_pay = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Сумма к выплате'
    )
    
    paid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Выплаченная сумма'
    )
    
    payment_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата выплаты'
    )
    
    payment_method = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Способ выплаты',
        help_text='Карта, наличные, и т.д.'
    )
    
    payment_note = models.TextField(
        blank=True,
        verbose_name='Примечание к оплате'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Статус'
    )
    
    marked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_payments',
        verbose_name='Отметил оплату'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    class Meta:
        verbose_name = '💰 Бонусы: Реестр выплат'
        verbose_name_plural = '💰 Бонусы: Реестр выплат'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['week_report', 'author']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f'{self.author.username} - {self.amount_to_pay}₽ ({self.get_status_display()})'


class AIBonusCommand(models.Model):
    """Команды от AI агента для управления бонусами"""
    
    COMMAND_TYPE_CHOICES = [
        ('update_formula', 'Обновить формулу'),
        ('add_penalty', 'Добавить штраф'),
        ('add_reward', 'Добавить премию'),
        ('adjust_bonus', 'Скорректировать бонус'),
        ('change_role_percentage', 'Изменить процент роли'),
    ]
    
    conversation = models.ForeignKey(
        'Asistent.AIConversation',
        on_delete=models.CASCADE,
        related_name='bonus_commands',
        verbose_name='Диалог'
    )
    
    message = models.ForeignKey(
        'Asistent.AIMessage',
        on_delete=models.CASCADE,
        related_name='bonus_commands',
        verbose_name='Сообщение'
    )
    
    command_type = models.CharField(
        max_length=50,
        choices=COMMAND_TYPE_CHOICES,
        verbose_name='Тип команды'
    )
    
    target_author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ai_bonus_commands',
        verbose_name='Целевой автор'
    )
    
    parameters = models.JSONField(
        default=dict,
        verbose_name='Параметры команды',
        help_text='JSON с параметрами для выполнения команды'
    )
    
    executed = models.BooleanField(default=False, verbose_name='Выполнена')
    executed_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата выполнения')
    
    result = models.JSONField(
        default=dict,
        verbose_name='Результат выполнения',
        help_text='Результат или ошибка выполнения'
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    
    class Meta:
        verbose_name = '🤖 AI: Команда по бонусам'
        verbose_name_plural = '🤖 AI: Команды по бонусам'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['conversation', '-created_at']),
            models.Index(fields=['executed']),
        ]
    
    def __str__(self):
        return f'{self.get_command_type_display()} - {self.created_at.date()}'