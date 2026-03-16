"""
Модели статистики и логов

GigaChatUsageStats - Статистика использования GigaChat API
GigaChatSettings - Настройки работы с GigaChat API
SystemLog - Системные логи
IntegrationEvent - Интеграционные события
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


class GigaChatUsageStats(models.Model):
    """Статистика использования GigaChat API по моделям"""
    
    model_name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Название модели",
        help_text="GigaChat, GigaChat-Max, GigaChat-Pro"
    )
    
    tokens_used = models.IntegerField(
        default=0,
        verbose_name="Токенов использовано"
    )
    
    tokens_remaining = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Токенов осталось"
    )
    
    total_requests = models.IntegerField(
        default=0,
        verbose_name="Всего запросов"
    )
    
    successful_requests = models.IntegerField(
        default=0,
        verbose_name="Успешных запросов"
    )
    
    failed_requests = models.IntegerField(
        default=0,
        verbose_name="Неудачных запросов"
    )
    
    # Дневная статистика и стоимость
    tokens_used_today = models.IntegerField(
        default=0,
        verbose_name="Токенов использовано сегодня",
        help_text="Счетчик токенов за текущий день (сбрасывается в 00:00)"
    )
    
    cost_today = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name="Стоимость сегодня (₽)",
        help_text="Расходы на API за текущий день"
    )
    
    cost_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name="Общая стоимость (₽)",
        help_text="Все расходы на API за все время"
    )
    
    last_daily_reset = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Последний сброс дневной статистики",
        help_text="Дата последнего сброса tokens_used_today и cost_today (в 00:00)"
    )
    
    last_check_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Последняя проверка"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания"
    )
    
    class Meta:
        verbose_name = "🤖 GigaChat: Статистика модели"
        verbose_name_plural = "🤖 GigaChat: Статистика моделей"
        ordering = ['model_name']
    
    def __str__(self):
        return f"{self.model_name}: {self.tokens_remaining or 0} токенов"
    
    @property
    def success_rate(self):
        """Процент успешных запросов"""
        if self.total_requests == 0:
            return 0
        return round((self.successful_requests / self.total_requests) * 100, 2)

    def reset_daily_counters_if_needed(self, save=True):
        """Сбрасывает дневные счетчики, если наступил новый день."""
        now = timezone.now()
        if not self.last_daily_reset or self.last_daily_reset.date() != now.date():
            self.tokens_used_today = 0
            self.cost_today = Decimal("0.00")
            self.last_daily_reset = now
            if save:
                self.save(update_fields=["tokens_used_today", "cost_today", "last_daily_reset"])

    def register_usage(self, tokens_used: int, price_per_million: Decimal) -> None:
        """Фиксирует расход токенов и стоимость запроса."""
        if tokens_used <= 0:
            return
        self.reset_daily_counters_if_needed(save=False)
        self.tokens_used += tokens_used
        self.tokens_used_today += tokens_used
        cost_increment = (Decimal(tokens_used) / Decimal(1_000_000)) * price_per_million
        self.cost_today += cost_increment
        self.cost_total += cost_increment
        self.last_check_at = timezone.now()
        self.save(
            update_fields=[
                "tokens_used",
                "tokens_used_today",
                "cost_today",
                "cost_total",
                "last_daily_reset",
                "last_check_at",
            ]
        )


class GigaChatSettings(models.Model):
    """Настройки работы с GigaChat API"""
    
    # УСТАРЕВШИЕ ПОЛЯ (не используются в логике, оставлены для совместимости)
    check_balance_after_requests = models.IntegerField(default=1, validators=[MinValueValidator(1)], verbose_name="Проверять баланс после N запросов", help_text="[УСТАРЕЛО] Только для ручной проверки в дашборде")
    current_model = models.CharField(max_length=50, default='GigaChat', verbose_name="Текущая модель", help_text="[УСТАРЕЛО] Только для отображения, не используется в логике")
    auto_switch_enabled = models.BooleanField(default=True, verbose_name="Автопереключение моделей", help_text="[УСТАРЕЛО] Не используется - переключения отключены")
    models_priority = models.JSONField(default=list, verbose_name="Приоритет моделей", help_text="[УСТАРЕЛО] Только для отображения")
    request_counter = models.IntegerField(default=0, verbose_name="Счётчик запросов", help_text="[УСТАРЕЛО] Не используется")
    
    # НОВЫЕ ПОЛЯ: Включение моделей и прайс-лист
    embeddings_enabled = models.BooleanField(default=True, verbose_name="Embeddings включен", help_text="Использовать GigaChat-Embeddings для RAG и векторного поиска")
    lite_enabled = models.BooleanField(default=True, verbose_name="Lite включен", help_text="Использовать GigaChat Lite для простых задач")
    pro_enabled = models.BooleanField(default=True, verbose_name="Pro включен", help_text="Использовать GigaChat Pro для средних задач")
    max_enabled = models.BooleanField(default=True, verbose_name="Max включен", help_text="Использовать GigaChat Max для сложных задач")
    
    # Прайс-лист (₽ за 1M токенов) для расчета стоимости
    price_embeddings = models.DecimalField(max_digits=10, decimal_places=2, default=40.00, verbose_name="Цена Embeddings (₽/1M)", help_text="10M токенов = 400₽ → 1M = 40₽")
    price_lite = models.DecimalField(max_digits=10, decimal_places=2, default=194.00, verbose_name="Цена Lite (₽/1M)", help_text="30M токенов = 5,820₽ → 1M = 194₽")
    price_pro = models.DecimalField(max_digits=10, decimal_places=2, default=1500.00, verbose_name="Цена Pro (₽/1M)", help_text="1M токенов = 1,500₽")
    price_max = models.DecimalField(max_digits=10, decimal_places=2, default=1950.00, verbose_name="Цена Max (₽/1M)", help_text="1M токенов = 1,950₽")
    
    # УСТАРЕВШИЕ ПОЛЯ (не используются - проверки лимитов отключены)
    lite_daily_limit = models.IntegerField(default=2_000_000, verbose_name="Дневной лимит Lite (токены)", help_text="[УСТАРЕЛО] Не используется - проверки лимитов отключены")
    pro_daily_limit = models.IntegerField(default=1_000_000, verbose_name="Дневной лимит Pro (токены)", help_text="[УСТАРЕЛО] Не используется - проверки лимитов отключены")
    max_daily_limit = models.IntegerField(default=500_000, verbose_name="Дневной лимит Max (токены)", help_text="[УСТАРЕЛО] Не используется - проверки лимитов отключены")
    
    task_failure_limit = models.IntegerField(default=5, verbose_name="Порог ошибок на задачу", help_text="Сколько ошибок подряд допускается для одного типа задачи")
    task_failure_window = models.IntegerField(default=30, verbose_name="Окно ошибок (минуты)", help_text="За какой период анализировать ошибки для circuit breaker")
    
    # Пороги для алертов (только для дашборда)
    alert_threshold_percent = models.IntegerField(default=20, validators=[MinValueValidator(1), MaxValueValidator(100)], verbose_name="Порог алерта (%)", help_text="Только для отображения в Dashboard")
    
    # УСТАРЕВШЕЕ ПОЛЕ (не используется - переключения отключены)
    preventive_switch_threshold = models.IntegerField(default=10, validators=[MinValueValidator(1), MaxValueValidator(100)], verbose_name="Порог превентивного переключения (%)", help_text="[УСТАРЕЛО] Не используется - переключения отключены")
    
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Последнее обновление")
    
    class Meta:
        verbose_name = "🤖 GigaChat: Настройки"
        verbose_name_plural = "🤖 GigaChat: Настройки"
    
    def __str__(self):
        return f"GigaChat Settings (текущая модель: {self.current_model})"
    
    def save(self, *args, **kwargs):
        # Гарантируем что всегда существует только одна запись с pk=1
        self.pk = 1
        super().save(*args, **kwargs)


class SystemLog(models.Model):
    """Системные логи - все логи Django, Celery, Asistent и других модулей"""
    
    LEVEL_CHOICES = [
        ('DEBUG', 'DEBUG'),
        ('INFO', 'INFO'),
        ('WARNING', 'WARNING'),
        ('ERROR', 'ERROR'),
        ('CRITICAL', 'CRITICAL'),
    ]
    
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name='Время события'
    )
    
    level = models.CharField(
        max_length=10,
        choices=LEVEL_CHOICES,
        db_index=True,
        verbose_name='Уровень'
    )
    
    logger_name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name='Имя логгера',
        help_text='Например: django, Asistent, celery'
    )
    
    message = models.TextField(
        verbose_name='Сообщение'
    )
    
    module = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        verbose_name='Модуль',
        help_text='Имя модуля где произошло событие'
    )
    
    function = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Функция',
        help_text='Имя функции где произошло событие'
    )
    
    line = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Номер строки'
    )
    
    process_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='ID процесса'
    )
    
    thread_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='ID потока'
    )
    
    extra_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Дополнительные данные',
        help_text='Дополнительная информация в формате JSON'
    )
    
    class Meta:
        verbose_name = '📋 Системный лог'
        verbose_name_plural = '📋 Системные логи'
        ordering = ['-timestamp']
        db_table = 'asistent_systemlog'
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['level', '-timestamp']),
            models.Index(fields=['logger_name', '-timestamp']),
            models.Index(fields=['module', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.level} [{self.logger_name}] {self.message[:50]}... ({self.timestamp.strftime('%Y-%m-%d %H:%M:%S')})"


class IntegrationEvent(models.Model):
    """Интеграционные события (GigaChat, Telegram и т.д.)"""
    
    SERVICE_CHOICES = [
        ("telegram", "Telegram"),
        ("gigachat", "GigaChat"),
        ("storage", "Хранилище"),
        ("other", "Другое"),
    ]
    
    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
    ]
    
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Дата")
    service = models.CharField(max_length=32, choices=SERVICE_CHOICES, default="other", verbose_name="Сервис")
    code = models.CharField(max_length=64, verbose_name="Код/статус")
    message = models.TextField(verbose_name="Сообщение")
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default="warning", verbose_name="Уровень")
    extra = models.JSONField(default=dict, blank=True, verbose_name="Доп. данные")
    
    class Meta:
        verbose_name = "⚙️ Интеграция: событие"
        verbose_name_plural = "⚙️ Интеграции: события"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"[{self.service}] {self.code} ({self.severity})"
