"""
Helper функции для AI Control Center Dashboard
Собирает все метрики и статистику для центрального хаба управления
"""
import logging
from typing import Dict, List, Optional
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)


def get_all_models_balance() -> Dict:
    """
    Получить реальный баланс ВСЕХ 4 моделей GigaChat через API
    
    Returns:
        Dict с балансами и процентами для каждой модели
    """
    from .gigachat_api import get_gigachat_client
    from .models import GigaChatUsageStats, GigaChatSettings
    
    # Лимиты моделей (для расчета процентов)
    limits = {
        'GigaChat': 30000000,            # 30M для Lite
        'GigaChat-Pro': 1000000,         # 1M для Pro
        'GigaChat-Max': 1000000,         # 1M для Max
        'GigaChat-Embeddings': 10000000, # 10M для Embeddings
    }
    
    try:
        # Получаем настройки (для порогов)
        settings, created = GigaChatSettings.objects.get_or_create(
            pk=1,
            defaults={
                'check_balance_after_requests': 1,
                'current_model': 'GigaChat',
                'auto_switch_enabled': True,
                'models_priority': ['GigaChat', 'GigaChat-Pro', 'GigaChat-Max'],
                'alert_threshold_percent': 20,
                'preventive_switch_threshold': 10,
            }
        )
        
        if created:
            logger.info("✨ Создана запись GigaChatSettings")
        
        # Пытаемся получить баланс через API
        client = get_gigachat_client()
        balances_raw = client.get_balance()
        
        # Формируем данные для каждой модели
        models_data = {}
        
        for model_name in ['GigaChat-Embeddings', 'GigaChat', 'GigaChat-Pro', 'GigaChat-Max']:
            # Получаем токены из API или из БД
            tokens_remaining = balances_raw.get(model_name, 0)
            
            # Если API не вернул токены, берём из БД
            if tokens_remaining == 0:
                stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
                if stats and stats.tokens_remaining:
                    tokens_remaining = stats.tokens_remaining
            
            limit = limits.get(model_name, 1000000)
            percent = (tokens_remaining / limit) * 100 if limit > 0 else 0
            
            # Определяем статус по порогам
            if percent >= settings.alert_threshold_percent:
                status = 'ok'
                status_icon = '✅'
                status_color = 'green'
            elif percent >= settings.preventive_switch_threshold:
                status = 'warning'
                status_icon = '⚠️'
                status_color = 'yellow'
            else:
                status = 'critical'
                status_icon = '🔴'
                status_color = 'red'
            
            # Получаем статистику из БД
            stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
            
            models_data[model_name] = {
                'name': model_name,
                'display_name': model_name.replace('GigaChat-', '').replace('GigaChat', 'Lite'),
                'tokens_remaining': tokens_remaining,
                'tokens_limit': limit,
                'percent': round(percent, 1),
                'status': status,
                'status_icon': status_icon,
                'status_color': status_color,
                'total_requests': stats.total_requests if stats else 0,
                'success_rate': stats.success_rate if stats else 0,
            }
        
        logger.info(f"✅ Баланс всех моделей получен")
        return models_data
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения балансов: {e}", exc_info=True)
        
        # FALLBACK: Возвращаем данные из БД (если API недоступен)
        models_data = {}
        for model_name in ['GigaChat-Embeddings', 'GigaChat', 'GigaChat-Pro', 'GigaChat-Max']:
            limit = limits.get(model_name, 1000000)
            
            # Берём последние данные из БД
            stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
            tokens_remaining = stats.tokens_remaining if stats and stats.tokens_remaining else 0
            percent = (tokens_remaining / limit) * 100 if limit > 0 else 0
            
            models_data[model_name] = {
                'name': model_name,
                'display_name': model_name.replace('GigaChat-', '').replace('GigaChat', 'Lite'),
                'tokens_remaining': tokens_remaining,
                'tokens_limit': limit,
                'percent': round(percent, 1),
                'status': 'unknown',
                'status_icon': '❓',
                'status_color': 'gray',
                'total_requests': stats.total_requests if stats else 0,
                'success_rate': stats.success_rate if stats else 0,
            }
        
        logger.warning("⚠️ Используются данные из БД (API недоступен)")
        return models_data


def calculate_costs(period: str = 'today') -> Dict:
    """
    Рассчитать стоимость использования GigaChat API
    
    Args:
        period: 'today', 'week', 'month' или 'total'
    
    Returns:
        Dict со стоимостью и детализацией по моделям
    """
    from .models import GigaChatUsageStats, GigaChatSettings
    
    try:
        settings = GigaChatSettings.objects.get(pk=1)
        
        # Прайс-лист
        prices = {
            'GigaChat': settings.price_lite,
            'GigaChat-Pro': settings.price_pro,
            'GigaChat-Max': settings.price_max,
            'GigaChat-Embeddings': settings.price_embeddings,
        }
        
        total_cost = Decimal('0.00')
        breakdown = {}
        
        # Получаем статистику по моделям
        for model_name, price_per_1m in prices.items():
            stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
            
            if not stats:
                breakdown[model_name] = Decimal('0.00')
                continue
            
            # Выбираем токены в зависимости от периода
            if period == 'today':
                tokens = stats.tokens_used_today
            elif period == 'total':
                tokens = stats.total_requests * 1000  # Примерная оценка
            else:
                tokens = stats.tokens_used_today  # Fallback
            
            # Рассчитываем стоимость
            # ИСПРАВЛЕНО: Конвертируем tokens в Decimal для совместимости типов
            tokens_decimal = Decimal(str(tokens))
            price_decimal = Decimal(str(price_per_1m)) if price_per_1m else Decimal('0')
            cost = (tokens_decimal / Decimal('1000000')) * price_decimal
            breakdown[model_name] = round(cost, 2)
            total_cost += cost
        
        # Прогноз на месяц (на основе сегодняшних трат)
        today_cost = sum([v for v in breakdown.values()])
        month_forecast = today_cost * 30 if period == 'today' else 0
        
        # Экономия (сравнение с использованием только Max для всех задач)
        if period == 'today':
            # Если бы все задачи были на Max
            total_requests_today = sum([
                GigaChatUsageStats.objects.filter(model_name=m).first().total_requests 
                for m in prices.keys() 
                if GigaChatUsageStats.objects.filter(model_name=m).exists()
            ])
            # ИСПРАВЛЕНО: Конвертируем в Decimal
            total_requests_decimal = Decimal(str(total_requests_today))
            price_max_decimal = Decimal(str(settings.price_max)) if settings.price_max else Decimal('0')
            cost_if_only_max = (total_requests_decimal * Decimal('1000') / Decimal('1000000')) * price_max_decimal
            savings_percent = ((cost_if_only_max - today_cost) / cost_if_only_max * 100) if cost_if_only_max > 0 else 0
        else:
            savings_percent = 0
        
        return {
            'total': round(total_cost, 2),
            'breakdown': breakdown,
            'period': period,
            'month_forecast': round(month_forecast, 2),
            'savings_percent': round(savings_percent, 1),
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка расчета стоимости: {e}")
        return {
            'total': 0,
            'breakdown': {},
            'period': period,
            'month_forecast': 0,
            'savings_percent': 0,
        }


def get_system_alerts() -> List[Dict]:
    """
    Системные алерты и предупреждения
    
    Returns:
        List алертов с приоритетами (critical/warning/info)
    """
    from .models import GigaChatUsageStats, GigaChatSettings
    from .models import TaskAssignment, ContentTask
    from django_celery_results.models import TaskResult
    
    alerts = []
    
    try:
        settings = GigaChatSettings.objects.get(pk=1)
        
        # 1. Проверка баланса моделей
        for model_name in ['GigaChat', 'GigaChat-Pro', 'GigaChat-Max', 'GigaChat-Embeddings']:
            stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
            
            if not stats or stats.tokens_remaining is None:
                alerts.append({
                    'level': 'warning',
                    'icon': '⚠️',
                    'title': f'{model_name}: баланс неизвестен',
                    'message': 'Выполните синхронизацию баланса',
                    'action': 'sync_balance',
                })
                continue
            
            # Лимиты
            limits = {
                'GigaChat': 30000000,
                'GigaChat-Pro': 1000000,
                'GigaChat-Max': 1000000,
                'GigaChat-Embeddings': 10000000,
            }
            
            limit = limits.get(model_name, 1000000)
            percent = (stats.tokens_remaining / limit) * 100
            
            if percent < settings.preventive_switch_threshold:
                alerts.append({
                    'level': 'critical',
                    'icon': '🔴',
                    'title': f'{model_name}: критически низкий баланс!',
                    'message': f'Осталось {stats.tokens_remaining:,} токенов ({percent:.1f}%)',
                    'action': 'top_up_tokens',
                })
            elif percent < settings.alert_threshold_percent:
                alerts.append({
                    'level': 'warning',
                    'icon': '🟡',
                    'title': f'{model_name}: низкий баланс',
                    'message': f'Осталось {stats.tokens_remaining:,} токенов ({percent:.1f}%)',
                    'action': 'monitor',
                })
        
        # 2. Статьи на модерации > 24 часа
        day_ago = timezone.now() - timedelta(hours=24)
        pending_assignments = TaskAssignment.objects.filter(
            status='submitted',
            submitted_at__lt=day_ago
        ).count()
        
        if pending_assignments > 0:
            alerts.append({
                'level': 'warning',
                'icon': '📝',
                'title': f'{pending_assignments} статей ждут модерации >24ч',
                'message': 'Проверьте задания на модерации',
                'action': 'check_moderation',
            })
        
        # 3. Ошибки Celery за последние 24 часа
        recent_failures = TaskResult.objects.filter(
            date_done__gte=day_ago,
            status='FAILURE'
        ).count()
        
        if recent_failures > 5:
            alerts.append({
                'level': 'warning',
                'icon': '⚙️',
                'title': f'Celery: {recent_failures} ошибок за 24ч',
                'message': 'Проверьте логи задач',
                'action': 'check_celery',
            })
        
        # 4. Успешное состояние (если нет алертов)
        if not alerts:
            alerts.append({
                'level': 'success',
                'icon': '✅',
                'title': 'Все системы работают нормально',
                'message': 'Проблем не обнаружено',
                'action': None,
            })
        
        return alerts
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения алертов: {e}")
        return [{
            'level': 'error',
            'icon': '❌',
            'title': 'Ошибка системы алертов',
            'message': str(e),
            'action': None,
        }]


def get_model_distribution(days: int = 7) -> Dict:
    """
    Распределение запросов по моделям GigaChat
    
    Args:
        days: За сколько дней собирать статистику
    
    Returns:
        Dict с распределением запросов по моделям
    """
    from .models import GigaChatUsageStats
    
    try:
        # Получаем статистику ТОЛЬКО основных моделей (без дубликатов)
        model_names = ['GigaChat-Embeddings', 'GigaChat', 'GigaChat-Pro', 'GigaChat-Max']
        all_stats = GigaChatUsageStats.objects.filter(model_name__in=model_names)
        
        total_requests = sum([s.total_requests for s in all_stats])
        
        distribution = []
        for stats in all_stats:
            percent = (stats.total_requests / total_requests * 100) if total_requests > 0 else 0
            
            # Нормализуем название для отображения
            display_name = stats.model_name.replace('GigaChat-', '')
            if stats.model_name == 'GigaChat':
                display_name = 'Lite'
            
            distribution.append({
                'model': stats.model_name,
                'display_name': display_name,
                'requests': stats.total_requests,
                'percent': round(percent, 1),
                'success_rate': stats.success_rate,
            })
        
        # Сортируем по количеству запросов
        distribution.sort(key=lambda x: x['requests'], reverse=True)
        
        return {
            'total_requests': total_requests,
            'models': distribution,
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения распределения: {e}")
        return {
            'total_requests': 0,
            'models': [],
        }


def get_navigation_stats() -> Dict:
    """
    Счетчики для 6 навигационных карточек Dashboard
    
    Returns:
        Dict со счетчиками всех AI-процессов
    """
    from .models import AITask, AISchedule, TaskAssignment, AIGeneratedArticle
    from blog.models import Post
    from donations.models import Donation
    from advertising.models import AdBanner
    
    try:
        # 1. AI Задачи
        # ИСПРАВЛЕНО: Проверяем существование таблицы AITask
        try:
            active_tasks = AITask.objects.filter(
                status__in=['pending', 'in_progress']
            ).count()
            
            today_start = timezone.now().replace(hour=0, minute=0, second=0)
            completed_today = AITask.objects.filter(
                status='completed',
                completed_at__gte=today_start
            ).count()
        except Exception as e:
            # Таблица не существует или ошибка доступа
            logger.warning(f"Таблица AITask недоступна: {e}")
            active_tasks = 0
            completed_today = 0
        
        # 2. Расписания генерации
        active_schedules = AISchedule.objects.filter(is_active=True).count()
        next_run = AISchedule.objects.filter(
            is_active=True,
            next_run__isnull=False
        ).order_by('next_run').first()
        
        # 3. Модерация
        pending_moderation = TaskAssignment.objects.filter(
            status='submitted'
        ).count()
        
        moderated_today = TaskAssignment.objects.filter(
            status__in=['approved', 'rejected'],
            reviewed_at__gte=today_start
        ).count() if hasattr(TaskAssignment, 'reviewed_at') else 0
        
        # 4. SEO Оптимизация
        total_posts = Post.objects.filter(status='published').count()
        with_faq = Post.objects.filter(
            status='published',
            content__icontains='faq-section'
        ).count()
        
        # Обновленных старых за последние 7 дней
        week_ago = timezone.now() - timedelta(days=7)
        refreshed = Post.objects.filter(
            updated__gte=week_ago,
            created__lt=week_ago  # Создана раньше, обновлена недавно
        ).count()
        
        # 5. Донаты
        pending_donations = Donation.objects.filter(
            status='pending'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # 6. Реклама
        active_banners = AdBanner.objects.filter(is_active=True).count() if hasattr(AdBanner, 'is_active') else 0
        
        return {
            'tasks': {
                'active': active_tasks,
                'completed_today': completed_today,
                'url': '/asistent/admin-panel/ai-message-log/',
            },
            'schedules': {
                'active': active_schedules,
                'next_run': next_run.next_run if next_run else None,
                'url': '/asistent/admin-panel/ai-schedules/',
            },
            'moderation': {
                'pending': pending_moderation,
                'moderated_today': moderated_today,
                'url': '/asistent/admin-panel/tasks/management/',
            },
            'seo': {
                'with_faq': with_faq,
                'total': total_posts,
                'refreshed': refreshed,
                'url': '/blog/',  # Список всех статей блога
            },
            'donations': {
                'pending_amount': float(pending_donations),
                'url': '/donations/list/',
            },
            'advertising': {
                'active_banners': active_banners,
                'url': '/asistent/admin-panel/',  # На главный Dashboard (пока нет отдельной страницы)
            },
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения навигационных счетчиков: {e}")
        return {}


def get_seo_dashboard_stats() -> Dict:
    """
    Детальная SEO статистика для Dashboard
    
    Returns:
        Dict с SEO метриками
    """
    from blog.models import Post
    
    try:
        total_posts = Post.objects.filter(status='published').count()
        
        # FAQ блоки
        with_faq = Post.objects.filter(
            status='published',
            content__icontains='faq-section'
        ).count()
        
        without_faq = total_posts - with_faq
        faq_percent = (with_faq / total_posts * 100) if total_posts > 0 else 0
        
        # SEO метаданные
        with_meta = Post.objects.filter(
            status='published'
        ).exclude(meta_title='').exclude(meta_title__isnull=True).count()
        
        # Обновленные старые статьи
        week_ago = timezone.now() - timedelta(days=7)
        old_date = timezone.now() - timedelta(days=180)
        
        refreshed_old = Post.objects.filter(
            created__lt=old_date,
            updated__gte=week_ago
        ).count()
        
        # Популярные старые (кандидаты на обновление)
        popular_old = Post.objects.filter(
            created__lt=old_date,
            views__gt=500
        ).count()
        
        return {
            'total_posts': total_posts,
            'with_faq': with_faq,
            'without_faq': without_faq,
            'faq_percent': round(faq_percent, 1),
            'with_meta': with_meta,
            'refreshed_old': refreshed_old,
            'popular_old_candidates': popular_old,
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения SEO статистики: {e}")
        return {}


def get_celery_health() -> Dict:
    """
    Статус Celery кластера
    
    Returns:
        Dict со статусом очереди
    """
    from django_celery_results.models import TaskResult
    from celery import current_app
    
    try:
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)
        
        # Используем inspect() для получения информации о воркерах
        inspect = current_app.control.inspect()
        active_tasks = inspect.active() or {}
        scheduled_tasks = inspect.scheduled() or {}
        
        # Подсчитываем активные задачи
        active_count = sum(len(tasks) for tasks in active_tasks.values())
        queued_count = sum(len(tasks) for tasks in scheduled_tasks.values())
        
        # Выполнено за час
        recent_success = TaskResult.objects.filter(
            date_done__gte=hour_ago,
            status='SUCCESS'
        ).count()
        
        # Ошибки за час
        recent_failures = TaskResult.objects.filter(
            date_done__gte=hour_ago,
            status='FAILURE'
        ).count()
        
        # Последняя задача
        last_task = TaskResult.objects.filter(
            status='SUCCESS'
        ).order_by('-date_done').first()
        
        # Определяем статус
        if active_count > 0 or recent_success > 0:
            status = 'running'
            status_message = f'Работает ({active_count} активных)'
        elif queued_count > 0:
            status = 'queued'
            status_message = f'Очередь ({queued_count} задач)'
        else:
            status = 'idle'
            status_message = 'Простаивает'
        
        return {
            'status': status,
            'status_message': status_message,
            'active_tasks': active_count,
            'queued_tasks': queued_count,
            'recent_success': recent_success,
            'recent_failures': recent_failures,
            'last_task_time': last_task.date_done if last_task else None,
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки Celery: {e}")
        return {
            'status': 'error',
            'status_message': f'Ошибка: {e}',
            'active_tasks': 0,
            'queued_tasks': 0,
            'recent_success': 0,
            'recent_failures': 0,
            'last_task_time': None,
        }


def get_usage_history_for_chart(days: int = 7) -> Dict:
    """
    История использования моделей для построения графика
    
    Args:
        days: За сколько дней
    
    Returns:
        Dict с данными для Chart.js
    """
    from .models import GigaChatUsageStats
    
    try:
        # Пока возвращаем базовые данные
        # TODO: Добавить историческую таблицу для детальных графиков
        
        models_data = []
        for model_name in ['GigaChat', 'GigaChat-Pro', 'GigaChat-Max', 'GigaChat-Embeddings']:
            stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
            
            models_data.append({
                'label': model_name.replace('GigaChat-', ''),
                'data': [stats.total_requests if stats else 0],  # Упрощенно
                'borderColor': _get_model_color(model_name),
                'tension': 0.1,
            })
        
        return {
            'labels': ['Сегодня'],  # Упрощенно, потом расширим
            'datasets': models_data,
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения истории: {e}")
        return {'labels': [], 'datasets': []}


def _get_model_color(model_name: str) -> str:
    """Возвращает цвет для модели на графике"""
    colors = {
        'GigaChat': '#3b82f6',           # Синий (Lite)
        'GigaChat-Pro': '#8b5cf6',       # Фиолетовый
        'GigaChat-Max': '#ef4444',       # Красный
        'GigaChat-Embeddings': '#10b981',# Зеленый
    }
    return colors.get(model_name, '#6b7280')