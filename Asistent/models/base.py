"""
Базовые миксины и утилиты для моделей
"""
from django.db import models
from django.utils import timezone


class TimestampMixin(models.Model):
    """Миксин для добавления created_at и updated_at"""
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Дата обновления')
    
    class Meta:
        abstract = True


class StatusMixin(models.Model):
    """Миксин для моделей со статусом"""
    STATUS_CHOICES = []
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        verbose_name='Статус'
    )
    
    class Meta:
        abstract = True
    
    def is_active_status(self):
        return self.status == 'active'
