"""
Представления для AI-Ассистента
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_POST
from django.db.models import Sum, Count, Q, F, ExpressionWrapper, DurationField, OuterRef, Subquery
from django.db.models.functions import Lower
from django.utils import timezone
from django.contrib import messages
from django.conf import settings
from django.urls import reverse
import logging
from urllib.parse import urlencode
import json
import ast
from types import SimpleNamespace
from celery.result import AsyncResult
from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
from django_celery_results.models import TaskResult

logger = logging.getLogger(__name__)

from .models import *
from .forms import ContentTaskForm
from Asistent.schedule.forms import AIScheduleForm, DjangoQScheduleForm
from Asistent.Test_Promot.forms import PromptTemplateForm
from .analytics import AIMetricsDashboard
from .dashboard_helpers import *
from datetime import date, timedelta, datetime
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.dateparse import parse_date
from Asistent.formatting import render_markdown, MarkdownPreset
from Asistent.services.notifications import notify_user
from Asistent.services.task_actions import (
    take_task as take_task_action,
    cancel_task as cancel_task_action,
    approve_task as approve_task_action,
    reject_task as reject_task_action,
)
from Asistent.schedule.presets import AI_SCHEDULE_PRESETS
from Asistent.schedule.models import AISchedule, AIScheduleRun
# Импорты пайплайнов удалены - система пайплайнов больше не используется
from Asistent.services import djangoq_monitor

SCHEDULE_STATUS_STYLES = {
    'success': {
        'label': 'Успешно',
        'badge_classes': 'bg-emerald-500/20 text-emerald-300',
    },
    'failed': {
        'label': 'Ошибка',
        'badge_classes': 'bg-rose-500/20 text-rose-300',
    },
    'partial': {
        'label': 'Частично',
        'badge_classes': 'bg-amber-500/20 text-amber-300',
    },
    'running': {
        'label': 'Выполняется',
        'badge_classes': 'bg-blue-500/20 text-blue-300',
    },
}

"""Возвращает локализованную строку времени или '—'"""
def _format_datetime(dt):
    """Возвращает локализованную строку времени или '—'"""
    if not dt:
        return '—'
    try:
        return timezone.localtime(dt).strftime('%d.%m.%Y %H:%M')
    except Exception:
        return dt.strftime('%d.%m.%Y %H:%M')

"""Возвращает подпись и CSS-классы для статуса запуска расписания"""
def _get_run_status_meta(status):
    """Возвращает подпись и CSS-классы для статуса запуска расписания"""
    if not status:
        return {'label': 'Нет данных', 'badge_classes': 'bg-gray-600/60 text-gray-200'}
    meta = SCHEDULE_STATUS_STYLES.get(status, None)
    if not meta:
        return {'label': status, 'badge_classes': 'bg-gray-600/60 text-gray-200'}
    return meta.copy()

"""Подготавливает данные статуса расписания для фронтенда"""
def _schedule_status_payload(schedule, latest_run=None):
    """Подготавливает данные статуса расписания для фронтенда"""
    if latest_run is None:
        latest_run = schedule.runs.order_by('-started_at').first()

    status_meta = _get_run_status_meta(latest_run.status if latest_run else None)

    return {
        'is_active': schedule.is_active,
        'latest_status': latest_run.status if latest_run else None,
        'latest_status_label': status_meta['label'],
        'latest_status_classes': status_meta['badge_classes'],
        'last_run_display': _format_datetime(latest_run.started_at if latest_run else None),
        'next_run_display': _format_datetime(schedule.next_run),
    }


"""Формирует список пресетов быстрого старта (без пайплайнов)."""
def _build_global_schedule_presets():
    """Формирует список пресетов быстрого старта (без пайплайнов)."""
    presets = []
    for preset in AI_SCHEDULE_PRESETS:
        item = preset.copy()
        # Удаляем pipeline_slug из пресетов
        item.pop('pipeline_slug', None)
        item.pop('pipeline_id', None)
        presets.append(item)
    return presets


"""Парсит строку времени в объект time."""
def _parse_time_value(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%H:%M').time()
    except (ValueError, TypeError):
        return None

"""Преобразует строку в целое число или возвращает None, если преобразование невозможно."""
def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _warn_legacy_queue(location):
    logger.warning("LEGACY queue 2026 migration fallback at %s", location)


def _lookup_legacy_djangoq_model(model_name, location):
    # LEGACY django_q 2026 migration
    _warn_legacy_queue(f"{location}:{model_name}")
    return None


def _safe_parse_payload(raw_value, default):
    if raw_value in (None, '', 'null'):
        return default
    if isinstance(raw_value, (dict, list, tuple)):
        return raw_value

    try:
        return json.loads(raw_value)
    except Exception:
        try:
            return ast.literal_eval(raw_value)
        except Exception:
            return default


def _to_legacy_task_view(task_result):
    kwargs_payload = _safe_parse_payload(task_result.task_kwargs, {})
    if not isinstance(kwargs_payload, dict):
        kwargs_payload = {}

    args_payload = _safe_parse_payload(task_result.task_args, [])
    if isinstance(args_payload, tuple):
        args_payload = list(args_payload)
    if not isinstance(args_payload, list):
        args_payload = [args_payload]

    started_at = task_result.date_started or task_result.date_created
    stopped_at = task_result.date_done or task_result.date_created
    time_taken = None
    if task_result.date_started and task_result.date_done:
        time_taken = (task_result.date_done - task_result.date_started).total_seconds()

    return SimpleNamespace(
        id=task_result.task_id,
        name=task_result.task_name or task_result.task_id,
        func=task_result.task_name or '',
        group=task_result.worker or '',
        kwargs=kwargs_payload,
        args=args_payload,
        lock=task_result.date_started if task_result.status == 'STARTED' else None,
        started=started_at,
        stopped=stopped_at,
        time_taken=time_taken,
        result=task_result.result,
        status=task_result.status,
        traceback=task_result.traceback,
    )


def _to_legacy_schedule_view(periodic_task):
    schedule_type = 'O'
    minutes = None
    cron = None

    if periodic_task.crontab_id:
        schedule_type = 'C'
        cron = str(periodic_task.crontab)
    elif periodic_task.interval_id:
        schedule_type = 'I'
        interval = periodic_task.interval
        if interval:
            multiplier = {
                IntervalSchedule.DAYS: 24 * 60,
                IntervalSchedule.HOURS: 60,
                IntervalSchedule.MINUTES: 1,
                IntervalSchedule.SECONDS: 1 / 60,
                IntervalSchedule.MICROSECONDS: 1 / 60000000,
            }
            minutes = int(interval.every * multiplier.get(interval.period, 1))

    return SimpleNamespace(
        id=periodic_task.id,
        name=periodic_task.name,
        func=periodic_task.task,
        schedule_type=schedule_type,
        minutes=minutes,
        cron=cron,
        args=periodic_task.args,
        kwargs=periodic_task.kwargs,
        next_run=periodic_task.start_time,
        repeats=-1,
    )


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
# Полная проверка здоровья Django-Q кластера
# ==================== ПРЕДСТАВЛЕНИЯ ====================

# Панель администратора с полными метриками AI
@staff_member_required
def admin_dashboard(request):
    """Панель администратора с полными метриками AI"""
    # Инициализируем Dashboard метрик AI
    dashboard = AIMetricsDashboard()
    
    # Получаем период для анализа (по умолчанию 30 дней)
    period_days = int(request.GET.get('period', 30))
    
    # Задания на проверке (TaskAssignment со статусом 'completed')
    tasks_for_review = TaskAssignment.objects.filter(
        status='completed'
    ).select_related('task', 'author').order_by('-submitted_at')[:10]
    
    # Просроченные задания
    overdue_tasks = ContentTask.objects.filter(
        deadline__lt=timezone.now(),
        status__in=['available', 'active']
    )[:10]
    
    # Базовая статистика заданий
    tasks_stats = {
        'tasks_for_review': TaskAssignment.objects.filter(status='completed').count(),
        'overdue_tasks': overdue_tasks.count(),
        'active_authors': TaskAssignment.objects.filter(
            status='in_progress'
        ).values('author').distinct().count(),
        'ai_articles_today': AIGeneratedArticle.objects.filter(
            created_at__date=date.today()
        ).count()
    }
    
    # Активные расписания AI
    ai_schedules = AISchedule.objects.filter(is_active=True)
    
    # Проверка статуса Django-Q
    djangoq_status = djangoq_monitor.check_djangoq_status()
    
    # ============================================================================
    # НОВЫЕ ДАННЫЕ: GigaChat Control Center
    # ============================================================================
    
    # Балансы всех 4 моделей
    gigachat_balances = get_all_models_balance()
    
    # Стоимость (сегодня, неделя, месяц)
    costs_today = calculate_costs('today')
    costs_week = calculate_costs('week')
    costs_month = calculate_costs('month')
    
    # Системные алерты
    system_alerts = get_system_alerts()
    
    # Распределение запросов по моделям
    model_distribution = get_model_distribution(days=period_days)
    
    # Навигационная статистика
    navigation_stats = get_navigation_stats()
    
    # SEO статистика
    seo_stats = get_seo_dashboard_stats()
    
    # Метрики гороскопов
    from Asistent.schedule.metrics import get_horoscope_metrics
    horoscope_metrics = get_horoscope_metrics(days=period_days)
    
    # Django-Q здоровье
    djangoq_health = get_djangoq_health()
    
    # История для Chart.js
    usage_history = get_usage_history_for_chart(days=period_days)
    
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    recent_schedule_runs = AIScheduleRun.objects.select_related('schedule').order_by('-started_at')[:10]

    def collect_status_counts(queryset):
        counts = queryset.values('status').annotate(total=Count('id'))
        mapping = {item['status']: item['total'] for item in counts}
        mapping['total'] = queryset.count()
        return mapping

    runs_today_qs = AIScheduleRun.objects.filter(started_at__gte=day_ago)
    runs_week_qs = AIScheduleRun.objects.filter(started_at__gte=week_ago)

    schedule_run_stats_today = collect_status_counts(runs_today_qs)
    schedule_run_stats_week = collect_status_counts(runs_week_qs)

    failing_schedules = (
        AIScheduleRun.objects.filter(status='failed', started_at__gte=week_ago)
        .values('schedule__name')
        .annotate(total=Count('id'))
        .order_by('-total')[:5]
    )

    latest_runs_map = {}
    for run in AIScheduleRun.objects.select_related('schedule').order_by('-started_at')[:200]:
        if run.schedule_id not in latest_runs_map:
            latest_runs_map[run.schedule_id] = run

    dashboard_schedules = []
    for schedule in AISchedule.objects.select_related('category', 'prompt_template').order_by('name'):
        latest_run = latest_runs_map.get(schedule.id)
        status_payload = _schedule_status_payload(schedule, latest_run)
        payload = {
            'schedule': schedule,
            'latest_run': latest_run,
        }
        payload.update(status_payload)
        dashboard_schedules.append(payload)
    
    # Получаем все метрики AI Dashboard
    context = {
        # Статус Django-Q (старый + новый)
        'djangoq_status': djangoq_status,
        'djangoq_health': djangoq_health,
        
        # Задания и расписания
        'tasks_for_review': tasks_for_review,
        'overdue_tasks': overdue_tasks,
        'tasks_stats': tasks_stats,
        'ai_schedules': ai_schedules,
        'recent_schedule_runs': recent_schedule_runs,
        'schedule_run_stats_today': schedule_run_stats_today,
        'schedule_run_stats_week': schedule_run_stats_week,
        'schedule_run_failures': failing_schedules,
        'dashboard_schedules': dashboard_schedules,
        'now': now,
        
        # Метрики AI Dashboard
        'daily_stats': dashboard.get_daily_stats(),
        'quality_metrics': dashboard.get_quality_metrics(),
        'ai_vs_human': dashboard.compare_ai_vs_human(),
        'schedule_performance': dashboard.get_schedule_performance(),
        'cost_analysis': dashboard.get_cost_analysis(),
        'trends': dashboard.get_trends(days=period_days),
        
        # ===== НОВЫЙ КОНТЕКСТ: GigaChat Control Center =====
        'gigachat_balances': gigachat_balances,
        'costs_today': costs_today,
        'costs_week': costs_week,
        'costs_month': costs_month,
        'system_alerts': system_alerts,
        'model_distribution': model_distribution,
        'navigation_stats': navigation_stats,
        'seo_stats': seo_stats,
        'horoscope_metrics': horoscope_metrics,
        'usage_history': usage_history,
        
        # Параметры
        'period_days': period_days,
        'available_periods': [7, 14, 30, 60, 90],
        
        # SEO-метатеги
        'page_title': 'AI Control Center — IdealImage.ru',
        'page_description': 'Центр управления AI-ассистентом: GigaChat мониторинг, балансы моделей, задания, расписания, метрики и SEO',
        'meta_keywords': 'админ панель AI, GigaChat, управление AI, задания AI, расписания AI, метрики, SEO',
        'og_title': 'AI Control Center — Панель администратора',
        'og_description': 'Полный контроль над AI-ассистентом на IdealImage.ru',
    }
    
    return render(request, 'Asistent/admin_dashboard.html', context)


# Календарь заданий
@staff_member_required
def task_calendar(request):
    """Календарь заданий"""
    tasks = ContentTask.objects.prefetch_related('assignments__author').all()
    
    # Преобразуем задания в формат для календаря
    events = []
    for task in tasks:
        # Получаем авторов через TaskAssignment
        assignments = task.assignments.filter(status='in_progress')
        assigned_authors = [assignment.author.username for assignment in assignments]
        assigned_to_str = ', '.join(assigned_authors) if assigned_authors else None
        
        events.append({
            'id': task.id,
            'title': task.title,
            'start': task.deadline.isoformat(),
            'color': {
                'available': '#28a745',
                'active': '#ffc107',
                'completed': '#6c757d',
                'cancelled': '#dc3545'
            }.get(task.status, '#6c757d'),
            'extendedProps': {
                'status': task.get_status_display(),
                'assigned_to': assigned_to_str,
                'reward': float(task.reward),
                'assignments_count': assignments.count()
            }
        })
    
    context = {
        'events': events
    }
    
    return render(request, 'Asistent/task_calendar.html', context)

# Создание нового задания
@staff_member_required
def create_task(request):
    """Создание нового задания"""
    if request.method == 'POST':
        form = ContentTaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.save()
            
            messages.success(request, f'✅ Задание "{task.title}" создано!')
            return redirect('asistent:tasks_management')
    else:
        form = ContentTaskForm()
    
    context = {
        'form': form,
        'is_edit': False,
        'page_title': 'Создание задания - IdealImage.ru',
        'page_description': 'Создание нового задания для авторов',
    }
    
    return render(request, 'Asistent/create_task.html', context)

# Редактирование задания
@staff_member_required
def edit_task(request, task_id):
    """Редактирование задания"""
    task = get_object_or_404(ContentTask, id=task_id)
    
    if request.method == 'POST':
        form = ContentTaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save()
            messages.success(request, f'✅ Задание "{task.title}" обновлено!')
            return redirect('asistent:tasks_management')
    else:
        form = ContentTaskForm(instance=task)
    
    context = {
        'form': form,
        'task': task,
        'is_edit': True,
        'page_title': f'Редактирование задания - IdealImage.ru' if True else 'Создание задания - IdealImage.ru',
        'page_description': f'Редактирование задания "{task.title}"' if True else 'Создание нового задания для авторов',
    }
    
    return render(request, 'Asistent/create_task.html', context)


# Отмена/снятие задания
@staff_member_required
@require_POST
def cancel_task(request, task_id):
    """Отмена/снятие задания"""
    task = get_object_or_404(ContentTask, id=task_id)
    task_title = task.title

    assignments_count = cancel_task_action(task)

    messages.success(request, f'✅ Задание "{task_title}" снято. Уведомлено авторов: {assignments_count}')
    return redirect('asistent:tasks_management')


# Страница управления заданиями
@staff_member_required
def tasks_management(request):
    """Страница управления заданиями"""
    from .models import TaskAssignment
    from Visitor.models import Donation
    from django.db.models import Sum, Count, Q
    
    # Все задания (кроме отмененных показываем с фильтром)
    show_cancelled = request.GET.get('show_cancelled', 'no') == 'yes'
    
    if show_cancelled:
        tasks = ContentTask.objects.all()
    else:
        tasks = ContentTask.objects.exclude(status='cancelled')
    
    tasks = tasks.select_related('created_by', 'category').order_by('-created_at')
    
    # Для каждого задания получаем детали
    tasks_data = []
    for task in tasks:
        assignments = TaskAssignment.objects.filter(task=task).select_related('author', 'article')
        
        # Общая сумма донатов
        total_donations = Donation.objects.filter(
            message__contains=f"Выполнение задания: {task.title}"
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        tasks_data.append({
            'task': task,
            'assignments': assignments,
            'total_donations': total_donations,
            'authors_taken': assignments.count(),
            'authors_completed': assignments.filter(status__in=['completed', 'approved']).count(),
            'authors_in_progress': assignments.filter(status='in_progress').count()
        })
    
    context = {
        'tasks_data': tasks_data,
        'show_cancelled': show_cancelled,
        'page_title': 'Управление заданиями - IdealImage.ru',
        'page_description': 'Полное управление заданиями для авторов с детальной статистикой',
    }
    
    return render(request, 'Asistent/tasks_management.html', context)


# Одобрить выполнение задания
@staff_member_required
@require_POST
def approve_task(request, task_id):
    """Одобрить выполнение задания"""
    task = get_object_or_404(ContentTask, id=task_id)

    if approve_task_action(task, request.user):
        messages.success(request, f'✅ Задание "{task.title}" одобрено! Автору начислено {task.reward}₽')
    else:
        messages.error(request, 'Не удалось одобрить задание.')

    return redirect('Visitor:superuser_dashboard')

# Отклонить выполнение задания
@staff_member_required
@require_POST
def reject_task(request, task_id):
    """Отклонить выполнение задания"""
    task = get_object_or_404(ContentTask, id=task_id)
    reason = request.POST.get('reason', 'Не указана')

    if reject_task_action(task, reason):
        messages.warning(request, f'⚠️ Задание "{task.title}" отклонено.')
    else:
        messages.error(request, 'Не удалось отклонить задание.')

    return redirect('Visitor:superuser_dashboard')


# Управление расписаниями AI и системными задачами Django-Q
@staff_member_required
def ai_schedules(request):
    """Управление расписаниями AI и системными задачами Django-Q"""

    current_tab = request.GET.get('tab', 'ai')

    # Параметры отображения и фильтрации
    requested_view = request.GET.get('view')
    if requested_view not in ('grid', 'table'):
        requested_view = request.session.get('ai_schedules_view', 'grid')
    request.session['ai_schedules_view'] = requested_view

    status_filter = request.GET.get('status', 'all')
    run_state_filter = request.GET.get('state', 'all')
    type_filter = request.GET.get('type', 'all')
    sort_param = request.GET.get('sort', 'created_at')
    sort_direction = request.GET.get('dir', 'desc')

    if sort_direction not in ('asc', 'desc'):
        sort_direction = 'desc'

    latest_status_subquery = AIScheduleRun.objects.filter(schedule=OuterRef('pk')).order_by('-started_at').values('status')[:1]

    # pipeline_log_subquery удален - система пайплайнов больше не используется

    base_ai_queryset = AISchedule.objects.all().annotate(
        _latest_status=Subquery(latest_status_subquery),
        # Аннотации пайплайнов удалены - система пайплайнов больше не используется
    )
    ai_total_count = base_ai_queryset.count()

    # Фильтрация
    ai_queryset = base_ai_queryset
    if status_filter == 'active':
        ai_queryset = ai_queryset.filter(is_active=True)
    elif status_filter == 'inactive':
        ai_queryset = ai_queryset.filter(is_active=False)

    if run_state_filter == 'running':
        ai_queryset = ai_queryset.filter(_latest_status='running')
    elif run_state_filter == 'stopped':
        ai_queryset = ai_queryset.exclude(_latest_status='running')

    if type_filter == 'system':
        ai_queryset = ai_queryset.filter(strategy_type='system')
    elif type_filter == 'non_system':
        ai_queryset = ai_queryset.exclude(strategy_type='system')

    # Сортировка
    sort_map = {
        'id': 'id',
        'created_at': 'created_at',
        'updated_at': 'updated_at',
        'name': '_name_sort',
        'category': '_category_sort',
        'strategy_type': 'strategy_type',
        'posting_frequency': 'posting_frequency',
        'last_run': 'last_run',
        'next_run': 'next_run',
        'status': 'is_active',
        'run_status': '_latest_status',
    }

    if sort_param == 'name':
        ai_queryset = ai_queryset.annotate(_name_sort=Lower('name'))
    elif sort_param == 'category':
        ai_queryset = ai_queryset.annotate(_category_sort=Lower('category__title'))

    sort_field = sort_map.get(sort_param, 'created_at')
    sort_prefix = '-' if sort_direction == 'desc' else ''
    ai_queryset = ai_queryset.order_by(f'{sort_prefix}{sort_field}', 'id').select_related('category')

    # LEGACY django_q 2026 migration: системные задачи берем из Celery Beat
    system_tasks = PeriodicTask.objects.select_related('interval', 'crontab').order_by('name')
    system_queryset = [_to_legacy_schedule_view(item) for item in system_tasks]
    system_total_count = len(system_queryset)

    base_params = {
        'tab': current_tab,
        'status': status_filter,
        'state': run_state_filter,
        'type': type_filter,
        'sort': sort_param,
        'dir': sort_direction,
    }
    filtered_params = {k: v for k, v in base_params.items() if v}

    grid_view_query = urlencode({**filtered_params, 'view': 'grid'})
    table_view_query = urlencode({**filtered_params, 'view': 'table'})

    reset_params = {'tab': current_tab}
    if requested_view:
        reset_params['view'] = requested_view
    reset_filters_query = urlencode(reset_params)

    filters_active = any([
        status_filter not in ('', 'all'),
        run_state_filter not in ('', 'all'),
        type_filter not in ('', 'all'),
        sort_param != 'created_at',
        sort_direction != 'desc',
    ])

    filter_params = {'tab': current_tab}
    if requested_view:
        filter_params['view'] = requested_view
    if status_filter not in ('', 'all'):
        filter_params['status'] = status_filter
    if run_state_filter not in ('', 'all'):
        filter_params['state'] = run_state_filter
    if type_filter not in ('', 'all'):
        filter_params['type'] = type_filter

    filter_querystring = urlencode(filter_params)

    context = {
        'current_tab': current_tab,
        'schedules': ai_queryset,
        'system_schedules': system_queryset,
        'ai_count': ai_total_count,
        'system_count': system_total_count,
        'page_title': 'Управление расписаниями - IdealImage.ru',
        'page_description': 'AI-генерация и системные задачи Celery Beat',
        'view_mode': requested_view,
        'status_filter': status_filter,
        'run_state_filter': run_state_filter,
        'type_filter': type_filter,
        'sort_param': sort_param,
        'sort_direction': sort_direction,
        'sort_options': [
            ('id', 'ID'),
            ('created_at', 'Дата создания'),
            ('updated_at', 'Дата обновления'),
            ('name', 'Название'),
            ('category', 'Категория'),
            ('strategy_type', 'Тип стратегии'),
            ('posting_frequency', 'Частота'),
            ('last_run', 'Последний запуск'),
            ('next_run', 'Следующий запуск'),
            ('status', 'Активность'),
            ('run_status', 'Статус выполнения'),
        ],
        'direction_options': [
            ('desc', 'По убыванию'),
            ('asc', 'По возрастанию'),
        ],
        'grid_view_query': grid_view_query,
        'table_view_query': table_view_query,
        'reset_filters_query': reset_filters_query,
        'filters_active': filters_active,
        'filter_querystring': filter_querystring,
    }

    return render(request, 'Asistent/ai_schedules.html', context)


@staff_member_required
def integration_events(request):
    """Страница событий интеграций"""
    from django.core.paginator import Paginator
    
    # Фильтры
    service_filter = request.GET.get('service', 'all')
    severity_filter = request.GET.get('severity', 'all')
    
    # Получаем все события
    events = IntegrationEvent.objects.all()
    
    # Применяем фильтры
    if service_filter != 'all':
        events = events.filter(service=service_filter)
    
    if severity_filter != 'all':
        events = events.filter(severity=severity_filter)
    
    # Сортировка по умолчанию: новые первые
    events = events.order_by('-created_at')
    
    # Пагинация
    paginator = Paginator(events, 50)  # 50 событий на страницу
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Статистика
    total_events = IntegrationEvent.objects.count()
    error_count = IntegrationEvent.objects.filter(severity='error').count()
    warning_count = IntegrationEvent.objects.filter(severity='warning').count()
    info_count = IntegrationEvent.objects.filter(severity='info').count()
    
    context = {
        'page_obj': page_obj,
        'events': page_obj,
        'total_events': total_events,
        'error_count': error_count,
        'warning_count': warning_count,
        'info_count': info_count,
        'service_filter': service_filter,
        'severity_filter': severity_filter,
        'service_choices': IntegrationEvent.SERVICE_CHOICES,
        'severity_choices': IntegrationEvent.SEVERITY_CHOICES,
    }
    
    return render(request, 'Asistent/integration_events.html', context)


@staff_member_required
@require_POST
def bulk_ai_schedules_action(request):
    """Массовые операции с расписаниями"""
    from django.http import JsonResponse
    
    try:
        # Получаем ID расписаний (может приходить в разных форматах)
        schedule_ids_raw = request.POST.getlist('schedule_ids[]')
        if not schedule_ids_raw:
            # Пробуем альтернативный формат
            schedule_ids_raw = request.POST.getlist('schedule_ids')
        
        # Преобразуем в список целых чисел
        schedule_ids = []
        for sid in schedule_ids_raw:
            try:
                schedule_ids.append(int(sid))
            except (ValueError, TypeError):
                logger.warning(f"Некорректный ID расписания: {sid}")
                continue
        
        action = request.POST.get('action')
        
        if not schedule_ids:
            error_msg = 'Не выбрано ни одного расписания'
            logger.warning(f"bulk_ai_schedules_action: {error_msg}, raw_ids={schedule_ids_raw}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                }, status=400)
            messages.warning(request, error_msg)
            return redirect('asistent:ai_schedules')
        
        if action not in ['activate', 'deactivate', 'delete', 'run']:
            error_msg = 'Неверное действие'
            logger.warning(f"bulk_ai_schedules_action: {error_msg}, action={action}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                }, status=400)
            messages.error(request, error_msg)
            return redirect('asistent:ai_schedules')
        
        logger.info(f"bulk_ai_schedules_action: action={action}, schedule_ids={schedule_ids}")
        
        schedules = AISchedule.objects.filter(id__in=schedule_ids)
        success_count = 0
        errors = []
        
        from Asistent.tasks import async_task
        from Asistent.schedule.tasks import run_specific_schedule
        
        for schedule in schedules:
            try:
                if action == 'activate':
                    schedule.is_active = True
                    schedule.save(update_fields=['is_active', 'updated_at'])
                    success_count += 1
                    logger.info(f"  ✅ Расписание {schedule.id} ({schedule.name}) активировано")
                elif action == 'deactivate':
                    schedule.is_active = False
                    schedule.save(update_fields=['is_active', 'updated_at'])
                    success_count += 1
                    logger.info(f"  ⏸️ Расписание {schedule.id} ({schedule.name}) деактивировано")
                elif action == 'delete':
                    schedule_name = schedule.name
                    schedule.delete()
                    success_count += 1
                    logger.info(f"  🗑️ Расписание {schedule.id} ({schedule_name}) удалено")
                elif action == 'run':
                    if not schedule.is_active:
                        errors.append(f'"{schedule.name}" неактивно')
                        continue
                    async_task(
                        run_specific_schedule,
                        schedule.id,
                        task_name=f'bulk_run_schedule_{schedule.id}'
                    )
                    success_count += 1
                    logger.info(f"  🚀 Расписание {schedule.id} ({schedule.name}) запущено")
            except Exception as e:
                error_msg = f'"{schedule.name}": {str(e)}'
                errors.append(error_msg)
                logger.error(f"  ❌ Ошибка при массовом действии {action} для расписания {schedule.id}: {e}", exc_info=True)
        
        messages_dict = {
            'activate': 'активировано',
            'deactivate': 'деактивировано',
            'delete': 'удалено',
            'run': 'запущено'
        }
        
        message = f'{success_count} расписание(й) {messages_dict[action]}'
        if errors:
            message += f'. Ошибок: {len(errors)}'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': message,
                'success_count': success_count,
                'errors': errors,
                'action': action,
                'schedule_ids': schedule_ids
            })
        
        if errors:
            messages.warning(request, f'⚠️ {message}')
            for error in errors[:5]:  # Показываем первые 5 ошибок
                messages.warning(request, f'  • {error}')
        else:
            messages.success(request, f'✅ {message}')
        
        return redirect('asistent:ai_schedules')
        
    except Exception as e:
        error_msg = f"Ошибка при массовых операциях: {e}"
        logger.error(error_msg, exc_info=True)
        
        # Логируем детали запроса для отладки
        logger.error(f"  POST данные: {dict(request.POST)}")
        logger.error(f"  Headers: {dict(request.headers)}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при выполнении операции: {str(e)}',
                'debug': {
                    'post_data': dict(request.POST),
                    'schedule_ids_raw': request.POST.getlist('schedule_ids[]') or request.POST.getlist('schedule_ids'),
                    'action': request.POST.get('action')
                }
            }, status=500)
        messages.error(request, f'❌ Ошибка: {str(e)}')
        return redirect('asistent:ai_schedules')


# Создание расписания AI
@staff_member_required
def create_ai_schedule(request):
    """Создание расписания AI - редирект на новую систему"""
    return redirect('schedule:schedule_create')


# Редактирование расписания AI
@staff_member_required
def edit_ai_schedule(request, schedule_id):
    """Редактирование расписания AI - редирект на новую систему"""
    return redirect('schedule:schedule_edit', schedule_id=schedule_id)


# Удаление расписания AI
@staff_member_required
@require_POST
@staff_member_required
@require_POST
def delete_ai_schedule(request, schedule_id):
    """Удаление расписания AI"""
    from django.http import JsonResponse
    
    schedule = get_object_or_404(AISchedule, id=schedule_id)
    schedule_name = schedule.name
    
    # Удаляем связанные AI-статьи если нужно
    from .models import AIGeneratedArticle
    articles_count = AIGeneratedArticle.objects.filter(schedule=schedule).count()
    
    schedule.delete()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': f'Расписание "{schedule_name}" удалено! (Также удалено {articles_count} записей истории)',
            'schedule_id': schedule_id,
            'removed': True
        })
    
    messages.success(
        request, 
        f'Расписание "{schedule_name}" удалено! '
        f'(Также удалено {articles_count} записей истории)'
    )
    return redirect('asistent:ai_schedules')


@staff_member_required
@require_POST
def api_schedule_preview(request):
    """Возвращает фактический datetime следующего запуска для заданных параметров."""
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'INVALID_JSON'}, status=400)

    interval_minutes = _safe_int(payload.get('interval_minutes'))
    if interval_minutes is not None and interval_minutes <= 0:
        interval_minutes = None

    weekday = _safe_int(payload.get('weekday'))
    if weekday is not None and weekday not in range(0, 7):
        weekday = None

    schedule = AISchedule(
        name=payload.get('name') or 'preview',
        schedule_kind=payload.get('schedule_kind') or 'daily',
        scheduled_time=_parse_time_value(payload.get('scheduled_time')),
        interval_minutes=interval_minutes,
        weekday=weekday,
        cron_expression=(payload.get('cron_expression') or '').strip(),
        articles_per_run=_safe_int(payload.get('articles_per_run')) or 1,
        is_active=bool(payload.get('is_active', True)),
    )

    try:
        next_run = schedule.calculate_next_run()
    except Exception as exc:  # pragma: no cover - защитная ветка
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    if not next_run:
        return JsonResponse({'success': False, 'error': 'UNABLE_TO_CALCULATE'}, status=400)

    response = {
        'success': True,
        'next_run': timezone.localtime(next_run).strftime('%d.%m.%Y %H:%M'),
        'iso': next_run.isoformat(),
    }

    if schedule.schedule_kind == 'interval' and schedule.interval_minutes:
        try:
            per_hour = (60 / schedule.interval_minutes) * max(schedule.articles_per_run, 1)
            response['per_hour'] = round(per_hour, 2)
        except ZeroDivisionError:
            response['per_hour'] = None

    return JsonResponse(response)


# Включение/отключение расписания AI
@staff_member_required
@require_POST
def toggle_ai_schedule(request, schedule_id):
    """Включение/отключение расписания AI"""
    schedule = get_object_or_404(AISchedule, id=schedule_id)
    
    # Переключаем статус
    schedule.is_active = not schedule.is_active
    schedule.save(update_fields=['is_active', 'updated_at'])
    
    status_text = 'включено' if schedule.is_active else 'отключено'
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        status_payload = _schedule_status_payload(schedule)
        status_payload.update({
            'success': True,
            'message': f'Расписание "{schedule.name}" {status_text}.',
            'toggle_label': 'Поставить на паузу' if schedule.is_active else 'Активировать',
        })
        return JsonResponse(status_payload)
    
    messages.success(request, f'Расписание "{schedule.name}" {status_text}!')
    return redirect('asistent:ai_schedules')


# Синхронизация расписаний Django-Q
@staff_member_required
def sync_schedules_ajax(request):
    """Синхронизация расписаний Django-Q"""
    from django.http import JsonResponse
    
    try:
        # Заглушка - функция для синхронизации расписаний
        return JsonResponse({
            'success': True,
            'message': 'Расписания синхронизированы'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# Страница оптимизации использования токенов
@staff_member_required
def token_optimization(request):
    """Страница оптимизации использования токенов"""
    from .models import GigaChatUsageStats
    
    # Получаем статистику из БД - модель хранит общую статистику по каждой модели
    model_stats = []
    
    for model_name in ['GigaChat', 'GigaChat-Pro', 'GigaChat-Max', 'GigaChat-Plus']:
        try:
            stats = GigaChatUsageStats.objects.get(model_name=model_name)
            model_stats.append({
                'model_name': model_name,
                'total_requests': stats.total_requests,
                'successful_requests': stats.successful_requests,
                'failed_requests': stats.failed_requests,
                'success_rate': stats.success_rate
            })
        except GigaChatUsageStats.DoesNotExist:
            # Если записи нет - показываем нули
            model_stats.append({
                'model_name': model_name,
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0,
                'success_rate': 0
            })
    
    return render(request, 'Asistent/token_optimization.html', {
        'title': 'Оптимизация токенов GigaChat',
        'page_title': 'Анализ затрат токенов - IdealImage.ru',
        'page_description': 'Анализ использования токенов GigaChat и рекомендации по оптимизации',
        'model_stats': model_stats,
    })

# API для анализа использования токенов
@staff_member_required
def api_token_analysis(request):
    """API для анализа использования токенов"""
    from django.http import JsonResponse
    from .models import GigaChatUsageStats
    
    try:
        # Получаем данные из GigaChatUsageStats
        total_requests = 0
        by_model = {}
        
        for model_name in ['GigaChat', 'GigaChat-Pro', 'GigaChat-Max']:
            try:
                stats = GigaChatUsageStats.objects.get(model_name=model_name)
                by_model[model_name] = stats.total_requests
                total_requests += stats.total_requests
            except GigaChatUsageStats.DoesNotExist:
                by_model[model_name] = 0
        
        return JsonResponse({
            'success': True,
            'data': {
                'total_requests': total_requests,
                'by_model': by_model,
                'by_task': {}
            }
        })
    except Exception as e:
        logger.error(f'Ошибка api_token_analysis: {e}')
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# Запустить расписание AI вручную
@staff_member_required
@require_POST
def run_ai_schedule(request, schedule_id):
    """Запустить расписание AI вручную"""
    from django.http import JsonResponse
    from Asistent.tasks import async_task
    
    schedule = get_object_or_404(AISchedule, id=schedule_id)
    
    try:
        # Проверяем активность расписания
        if not schedule.is_active:
            error_msg = f'Расписание "{schedule.name}" неактивно. Включите его перед запуском.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                }, status=400)
            messages.warning(request, f'⚠️ {error_msg}')
            return redirect('asistent:ai_schedules')
        
        # Запускаем расписание через Celery-совместимый async_task wrapper
        from Asistent.schedule.tasks import run_specific_schedule
        queued_count = None
        active_count = None
        
        # Запускаем асинхронно через Celery wrapper
        try:
            task_id = async_task(
                run_specific_schedule,
                schedule_id,
                task_name=f'manual_run_schedule_{schedule_id}'
            )
            
            logger.info(
                f"✅ Расписание {schedule.name} (ID: {schedule_id}) запущено вручную через Celery wrapper. "
                f"Task ID: {task_id}"
            )
        except Exception as task_error:
            logger.error(f"❌ Ошибка при добавлении задачи в очередь Django-Q: {task_error}", exc_info=True)
            error_msg = f'Ошибка при добавлении задачи в очередь: {str(task_error)}'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': error_msg,
                    'djangoq_status': {
                        'queued': queued_count,
                        'active': active_count
                    }
                }, status=500)
            messages.error(request, f'❌ {error_msg}')
            return redirect('asistent:ai_schedules')
        
        # Для AJAX запросов возвращаем JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            status_payload = _schedule_status_payload(schedule)
            status_payload.update({
                'success': True,
                'message': f'🚀 Запущена генерация статей для "{schedule.name}". Задача добавлена в очередь Celery.',
                'schedule_id': schedule_id,
                'schedule_name': schedule.name,
            })
            return JsonResponse({
                **status_payload
            })
        
        # Для обычных запросов - редирект
        # Определяем откуда пришел запрос
        referer = request.META.get('HTTP_REFERER', '')
        if 'superuser/dashboard' in referer or '/visitor/superuser/' in referer:
            redirect_url = 'Visitor:superuser_dashboard'
        else:
            redirect_url = 'asistent:ai_schedules'
        
        messages.success(request, f'🚀 Запущена генерация статей для "{schedule.name}". Задача добавлена в очередь Celery.')
        return redirect(redirect_url)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске расписания {schedule_id}: {e}", exc_info=True)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': f'Ошибка при запуске: {str(e)}'
            }, status=500)
        
        # Для обычных запросов - редирект с сообщением об ошибке
        messages.error(request, f'❌ Ошибка при запуске: {str(e)}')
        
        # Определяем откуда пришел запрос
        referer = request.META.get('HTTP_REFERER', '')
        if 'superuser/dashboard' in referer or '/visitor/superuser/' in referer:
            redirect_url = 'Visitor:superuser_dashboard'
        else:
            redirect_url = 'asistent:ai_schedules'
        
        return redirect(redirect_url)


# ============================================================
# CRUD для системных задач Django-Q Schedule
# ============================================================
# Создание системной задачи Django-Q
@staff_member_required
def create_system_schedule(request):
    """Создание системной задачи Django-Q"""
    from django.utils import timezone
    
    if request.method == 'POST':
        form = DjangoQScheduleForm(request.POST)
        if form.is_valid():
            try:
                schedule_type = form.cleaned_data['schedule_type']
                interval = None
                crontab = None

                if schedule_type == 'I':
                    minutes = form.cleaned_data['minutes'] or 60
                    interval, _ = IntervalSchedule.objects.get_or_create(
                        every=max(1, minutes),
                        period=IntervalSchedule.MINUTES,
                    )
                elif schedule_type == 'C':
                    cron_value = (form.cleaned_data['cron'] or '').split()
                    if len(cron_value) != 5:
                        messages.error(request, 'Cron должен быть в формате: минута час день месяц день_недели')
                        return render(request, 'Asistent/create_system_schedule.html', {'form': form})
                    crontab, _ = CrontabSchedule.objects.get_or_create(
                        minute=cron_value[0],
                        hour=cron_value[1],
                        day_of_month=cron_value[2],
                        month_of_year=cron_value[3],
                        day_of_week=cron_value[4],
                    )
                else:
                    interval, _ = IntervalSchedule.objects.get_or_create(
                        every=1,
                        period=IntervalSchedule.DAYS,
                    )

                schedule = PeriodicTask.objects.create(
                    name=form.cleaned_data['name'],
                    task=form.cleaned_data['func'],
                    interval=interval,
                    crontab=crontab,
                    args=form.cleaned_data.get('args') or '[]',
                    kwargs=form.cleaned_data.get('kwargs') or '{}',
                    start_time=form.cleaned_data.get('next_run') or timezone.now(),
                    enabled=True,
                )
                
                messages.success(request, f'Системная задача "{schedule.name}" создана!')
                return redirect('asistent:ai_schedules' + '?tab=system')
                
            except Exception as e:
                messages.error(request, f'Ошибка создания задачи: {str(e)}')
                logger.error(f'Error creating system schedule: {e}')
    else:
        form = DjangoQScheduleForm()
    
    context = {
        'form': form,
        'is_edit': False,
        'page_title': 'Создание системной задачи - IdealImage.ru',
        'page_description': 'Создание новой задачи Celery',
    }
    
    return render(request, 'Asistent/create_system_schedule.html', context)

# Редактирование системной задачи Django-Q
@staff_member_required
def edit_system_schedule(request, schedule_id):
    """Редактирование системной задачи Django-Q"""
    schedule = get_object_or_404(PeriodicTask, id=schedule_id)
    
    if request.method == 'POST':
        form = DjangoQScheduleForm(request.POST)
        if form.is_valid():
            try:
                schedule.name = form.cleaned_data['name']
                schedule.task = form.cleaned_data['func']
                schedule.args = form.cleaned_data.get('args') or '[]'
                schedule.kwargs = form.cleaned_data.get('kwargs') or '{}'
                schedule.start_time = form.cleaned_data.get('next_run') or schedule.start_time

                schedule_type = form.cleaned_data['schedule_type']
                schedule.interval = None
                schedule.crontab = None

                if schedule_type == 'I':
                    minutes = form.cleaned_data['minutes'] or 60
                    schedule.interval, _ = IntervalSchedule.objects.get_or_create(
                        every=max(1, minutes),
                        period=IntervalSchedule.MINUTES,
                    )
                elif schedule_type == 'C':
                    cron_value = (form.cleaned_data['cron'] or '').split()
                    if len(cron_value) != 5:
                        messages.error(request, 'Cron должен быть в формате: минута час день месяц день_недели')
                        return render(
                            request,
                            'Asistent/create_system_schedule.html',
                            {'form': form, 'schedule': _to_legacy_schedule_view(schedule), 'is_edit': True},
                        )
                    schedule.crontab, _ = CrontabSchedule.objects.get_or_create(
                        minute=cron_value[0],
                        hour=cron_value[1],
                        day_of_month=cron_value[2],
                        month_of_year=cron_value[3],
                        day_of_week=cron_value[4],
                    )
                else:
                    schedule.interval, _ = IntervalSchedule.objects.get_or_create(
                        every=1,
                        period=IntervalSchedule.DAYS,
                    )
                
                schedule.save()
                
                messages.success(request, f'Системная задача "{schedule.name}" обновлена!')
                return redirect('asistent:ai_schedules' + '?tab=system')
                
            except Exception as e:
                messages.error(request, f'Ошибка обновления задачи: {str(e)}')
                logger.error(f'Error updating system schedule: {e}')
    else:
        schedule_type = 'O'
        minutes = None
        cron = ''
        if schedule.interval_id:
            schedule_type = 'I'
            if schedule.interval.period == IntervalSchedule.MINUTES:
                minutes = schedule.interval.every
        if schedule.crontab_id:
            schedule_type = 'C'
            cron = str(schedule.crontab)

        initial_data = {
            'name': schedule.name,
            'func': schedule.task,
            'schedule_type': schedule_type,
            'minutes': minutes,
            'cron': cron,
            'args': schedule.args,
            'kwargs': schedule.kwargs if schedule.kwargs else '',
            'repeats': -1,
            'next_run': schedule.start_time,
        }
        form = DjangoQScheduleForm(initial=initial_data)
    
    context = {
        'form': form,
        'schedule': _to_legacy_schedule_view(schedule),
        'is_edit': True,
        'page_title': f'Редактирование задачи - IdealImage.ru',
        'page_description': f'Редактирование системной задачи "{schedule.name}"',
    }
    
    return render(request, 'Asistent/create_system_schedule.html', context)

# Удаление системной задачи Django-Q
@staff_member_required
@require_POST
def delete_system_schedule(request, schedule_id):
    """Удаление системной задачи Django-Q"""
    schedule = get_object_or_404(PeriodicTask, id=schedule_id)
    schedule_name = schedule.name
    
    schedule.delete()
    
    messages.success(request, f'Системная задача "{schedule_name}" удалена!')
    return redirect('asistent:ai_schedules' + '?tab=system')

# Журнал уведомлений AI-агента
@staff_member_required
def ai_message_log(request):
    """Журнал уведомлений AI-агента"""
    from .models import AIMessage, AIConversation
    from django.core.paginator import Paginator
    from datetime import timedelta
    
    # Фильтры
    role_filter = request.GET.get('role', '')
    conversation_filter = request.GET.get('conversation', '')
    period_filter = request.GET.get('period', 'week')
    
    # Базовый запрос
    messages_query = AIMessage.objects.select_related('conversation', 'conversation__admin').order_by('-timestamp')
    
    # Применяем фильтры
    if role_filter:
        messages_query = messages_query.filter(role=role_filter)
    
    if conversation_filter:
        messages_query = messages_query.filter(conversation_id=conversation_filter)
    
    # Фильтр по периоду
    if period_filter == 'today':
        messages_query = messages_query.filter(timestamp__date=timezone.now().date())
    elif period_filter == 'week':
        week_ago = timezone.now() - timedelta(days=7)
        messages_query = messages_query.filter(timestamp__gte=week_ago)
    elif period_filter == 'month':
        month_ago = timezone.now() - timedelta(days=30)
        messages_query = messages_query.filter(timestamp__gte=month_ago)
    # 'all' - без фильтра
    
    # Пагинация
    paginator = Paginator(messages_query, 50)
    page_number = request.GET.get('page', 1)
    messages_list = paginator.get_page(page_number)
    
    # Статистика
    stats = {
        'total': messages_query.count(),
        'from_ai': messages_query.filter(role='assistant').count(),
        'from_user': messages_query.filter(role='user').count(),
        'system': messages_query.filter(role='system').count(),
    }
    
    # Все диалоги для фильтра
    conversations = AIConversation.objects.all().order_by('-created_at')
    
    context = {
        'messages_list': messages_list,
        'conversations': conversations,
        'stats': stats,
        'page_title': 'Журнал AI-агента - IdealImage.ru',
        'page_description': 'Полная история сообщений и уведомлений от AI-ассистента',
    }
    
    return render(request, 'Asistent/ai_message_log.html', context)

# Очистка журнала AI-сообщений
@staff_member_required
@require_POST
def clear_ai_messages(request):
    """Очистка журнала AI-сообщений"""
    from .models import AIMessage
    
    count = AIMessage.objects.all().count()
    AIMessage.objects.all().delete()
    
    messages.success(request, f'🗑️ Удалено {count} сообщений из журнала')
    return redirect('asistent:ai_message_log')


# API для запуска Django-Q Cluster из веб-интерфейса
@staff_member_required
@require_POST
def api_start_djangoq(request):
    """API для запуска Django-Q Cluster из веб-интерфейса"""
    try:
        status = djangoq_monitor.check_djangoq_status()
        if status["is_running"]:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Django-Q Cluster уже работает",
                }
            )

        result = djangoq_monitor.start_djangoq_cluster()
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "unknown error")

        pid = result.get("pid")
        djangoq_monitor.notify_qcluster_alert(
            f"Кластер запущен из веб-интерфейса (PID {pid})",
            severity="warning",
        )
        return JsonResponse(
            {
                "success": True,
                "message": f"Django-Q Cluster запущен! (PID: {pid})\nОбновите страницу через 3 секунды.",
                "pid": pid,
            }
        )
    except Exception as exc:
        logger.error("Ошибка запуска Django-Q: %s", exc)
        djangoq_monitor.notify_qcluster_alert(f"Не удалось запустить Django-Q: {exc}", severity="error")
        return JsonResponse(
            {
                "success": False,
                "error": f"Не удалось запустить Django-Q автоматически. Ошибка: {exc}\nЗапустите вручную: python manage.py qcluster",
            },
            status=500,
        )


# API для получения статуса Django-Q (для AJAX-обновлений)
def api_djangoq_status(request):
    """API для получения статуса Django-Q (для AJAX-обновлений)"""
    try:
        status = djangoq_monitor.check_djangoq_status()
        
        # Преобразуем last_task в сериализуемый формат
        if status.get('last_task'):
            from django.utils.timesince import timesince
            status['last_task_info'] = {
                'name': status['last_task'].name if hasattr(status['last_task'], 'name') else 'Unknown',
                'stopped_ago': timesince(status['last_task'].stopped) if status['last_task'].stopped else 'N/A'
            }
            # Удаляем объект, чтобы избежать ошибок сериализации
            del status['last_task']
        
        # Преобразуем checked_at в строку
        if status.get('checked_at'):
            status['checked_at'] = status['checked_at'].isoformat()
        
        return JsonResponse(status)
        
    except Exception as e:
        logger.error(f"Ошибка API проверки Django-Q: {e}")
        return JsonResponse({
            'is_running': False,
            'error': str(e),
            'status_message': f'❌ Ошибка: {str(e)}'
        }, status=500)


# Запустить расписание из админки Django (GET запрос)
@staff_member_required
def run_schedule_now(request, schedule_id):
    """Запустить расписание из админки Django (GET запрос)"""
    from django.urls import reverse
    
    schedule = get_object_or_404(AISchedule, id=schedule_id)
    admin_changelist_url = reverse('admin:Asistent_aischedule_changelist')
    
    # Проверки перед запуском
    if not schedule.is_active:
        messages.warning(request, f'⚠️ Расписание "{schedule.name}" не активно! Включите его перед запуском.')
        return redirect(admin_changelist_url)
    
    if not schedule.source_urls and not schedule.prompt_template:
        messages.error(request, f'❌ Расписание "{schedule.name}" не содержит источников или шаблона! Добавьте данные перед запуском.')
        return redirect(admin_changelist_url)
    
    if not schedule.category:
        messages.error(request, f'❌ Не выбрана категория для расписания "{schedule.name}"!')
        return redirect(admin_changelist_url)
    
    try:
        # ШАГ 1: Отправка задачи в очередь Celery
        from Asistent.tasks import async_task
        task_id = async_task(
            'Asistent.tasks.run_specific_schedule',
            schedule_id,
            task_name=f'schedule:{schedule_id}'
        )
        
        # Успешное создание задачи
        messages.success(
            request,
            f'🚀 Задача отправлена в очередь Celery<br>'
            f'📋 Расписание: "{schedule.name}"<br>'
            f'🆔 Task ID: {task_id}<br>'
            f'📊 Будет создано статей: {schedule.articles_per_run}<br>'
            f'⏱️ Ожидайте результат в течение 2-5 минут'
        )
        
        if schedule.prompt_template:
            messages.info(
                request,
                f'🔄 ШАГ 2/4: Celery обрабатывает задачу...<br>'
                f'📥 Парсинг источников ({len(schedule.get_source_urls_list())} URL)<br>'
                f'🤖 Генерация статей через GigaChat AI<br>'
                f'💾 Сохранение в базу данных<br>'
                f'👉 Следите за задачами: /admin/django_celery_results/taskresult/'
            )
        
        blog_posts_url = reverse('admin:blog_post_changelist') + '?author__id=23'
        ai_articles_url = reverse('admin:Asistent_aigeneratedarticle_changelist')
        
        messages.info(
            request,
            f'📍 Где найти результат:<br>'
            f'✓ Статьи: <a href="{blog_posts_url}">Блог → Посты (автор: ai_assistant)</a><br>'
            f'✓ История: <a href="{ai_articles_url}">AI-Ассистент → AI-статьи</a><br>'
            f'✓ Логи: logs\\celery_worker.log'
        )
        
    except Exception as e:
        messages.error(request, f'❌ Ошибка при запуске: {str(e)}')
    
    # Возвращаемся на страницу списка расписаний в админке
    return redirect(admin_changelist_url)


# API: Проверка статуса задачи AI-агента
# API endpoints для AJAX-запросов
@login_required
def api_task_status(request, task_id):
    """API: Проверка статуса задачи AI-агента"""
    from django.http import JsonResponse
    from .models import AITask
    
    try:
        task = AITask.objects.get(id=task_id)
        
        # Получаем информацию о задаче
        response_data = {
            'task_id': task_id,
            'status': task.status,  # pending, running, completed, failed
            'progress_percentage': task.progress_percentage or 0,
            'progress_description': task.progress_description or '',
            'completed': task.status == 'completed',
            'failed': task.status == 'failed',
        }
        
        # Дополнительная информация
        if task.status == 'completed':
            response_data['result'] = task.result
            response_data['completed_at'] = task.completed_at.isoformat() if task.completed_at else None
        elif task.status == 'failed':
            response_data['error'] = task.error_message
        elif task.status == 'running':
            response_data['started_at'] = task.started_at.isoformat() if task.started_at else None
            
        return JsonResponse(response_data)
        
    except AITask.DoesNotExist:
        return JsonResponse({
            'error': 'Задача не найдена',
            'status': 'NOT_FOUND'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'status': 'ERROR'
        }, status=500)

# API: Список доступных заданий
@login_required
def api_available_tasks(request):
    """API: Список доступных заданий"""
    tasks = ContentTask.objects.filter(status='available')
    
    data = [{
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'reward': float(task.reward),
        'deadline': task.deadline.isoformat(),
        'required_word_count': task.required_word_count
    } for task in tasks]
    
    return JsonResponse({'tasks': data})


# API: Мои задания
@login_required
def api_my_tasks(request):
    """API: Мои задания"""
    tasks = ContentTask.objects.filter(
        assigned_to=request.user
    ).exclude(status__in=['completed', 'available'])
    
    data = [{
        'id': task.id,
        'title': task.title,
        'status': task.status,
        'status_display': task.get_status_display(),
        'deadline': task.deadline.isoformat(),
        'is_overdue': task.is_overdue
    } for task in tasks]
    
    return JsonResponse({'tasks': data})

# API: Уведомления
@login_required
def api_notifications(request):
    """API: Уведомления"""
    notifications = AuthorNotification.objects.filter(
        recipient=request.user,
        is_read=False
    ).order_by('-created_at')[:10]
    
    data = [{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'type': n.notification_type,
        'created_at': n.created_at.isoformat()
    } for n in notifications]
    
    return JsonResponse({
        'notifications': data,
        'count': notifications.count()
    })

# Список шаблонов промптов с поиском и сортировкой
@staff_member_required
def prompt_templates_list(request):
    """Список шаблонов промптов с поиском и сортировкой"""
    from .models import PromptTemplate
    from django.db.models import Q
    
    # Параметры фильтрации
    view_mode = request.GET.get('view', 'cards')  # cards или table
    search = request.GET.get('search', '')
    category = request.GET.get('category', '')
    sort_by = request.GET.get('sort', '-created_at')
    
    # Базовый запрос (usage_count уже есть в модели)
    templates = PromptTemplate.objects.all()
    
    # Поиск
    if search:
        templates = templates.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(template__icontains=search)
        )
    
    # Фильтр по категории
    if category:
        templates = templates.filter(category=category)
    
    # Сортировка
    templates = templates.order_by(sort_by)
    
    # Категории для фильтра
    categories = PromptTemplate.objects.values_list('category', flat=True).distinct()
    
    return render(request, 'Asistent/prompt_templates_list.html', {
        'templates': templates,
        'view_mode': view_mode,
        'search': search,
        'category': category,
        'sort_by': sort_by,
        'categories': categories,
        'title': 'Шаблоны промптов',
        'page_title': 'Управление шаблонами промптов - IdealImage.ru',
        'page_description': 'Управление AI промптами для генерации контента',
    })


# Создание нового шаблона промпта
@staff_member_required
def prompt_template_create(request):
    """Создание нового шаблона промпта"""
    from .models import PromptTemplate
    
    if request.method == 'POST':
        form = PromptTemplateForm(request.POST, request.FILES)
        if form.is_valid():
            template = form.save(commit=False)
            change_summary = form.cleaned_data.get('change_summary') or 'Создание шаблона'
            template.save(user=request.user, change_summary=change_summary)
            form.save_m2m()
            messages.success(request, f'Шаблон "{template.name}" успешно создан!')
            return redirect('asistent:prompt_templates_list')
    else:
        form = PromptTemplateForm()
    
    return render(request, 'Asistent/prompt_template_edit.html', {
        'form': form,
        'is_create': True,
        'versions': [],
        'title': 'Создание шаблона промпта',
        'page_title': 'Новый шаблон промпта - IdealImage.ru',
        'page_description': 'Создание нового шаблона промпта для AI генерации контента',
    })


# Редактирование шаблона промпта
@staff_member_required
def prompt_template_edit(request, template_id):
    """Редактирование шаблона промпта"""
    from .models import PromptTemplate
    
    template = get_object_or_404(PromptTemplate, id=template_id)
    
    if request.method == 'POST':
        form = PromptTemplateForm(request.POST, request.FILES, instance=template)
        if form.is_valid():
            template = form.save(commit=False)
            change_summary = form.cleaned_data.get('change_summary', '').strip()
            template.save(user=request.user, change_summary=change_summary)
            form.save_m2m()
            messages.success(request, f'Шаблон "{template.name}" успешно обновлён!')
            return redirect('asistent:prompt_templates_list')
    else:
        form = PromptTemplateForm(instance=template)
    
    return render(request, 'Asistent/prompt_template_edit.html', {
        'form': form,
        'template': template,
        'is_create': False,
        'versions': template.versions.select_related('created_by')[:10],
        'title': f'Редактирование: {template.name}',
        'page_title': f'Редактирование шаблона: {template.name} - IdealImage.ru',
        'page_description': f'Редактирование шаблона промпта {template.name}',
    })


# Удаление шаблона промпта
@staff_member_required
def prompt_template_delete(request, template_id):
    """Удаление шаблона промпта"""
    from .models import PromptTemplate
    
    template = get_object_or_404(PromptTemplate, id=template_id)
    
    if request.method == 'POST':
        template_name = template.name
        template.delete()
        messages.success(request, f'Шаблон "{template_name}" удалён!')
        return redirect('asistent:prompt_templates_list')
    
    return render(request, 'Asistent/prompt_template_delete.html', {
        'template': template,
        'title': f'Удаление: {template.name}',
        'page_title': f'Удаление шаблона: {template.name} - IdealImage.ru',
        'page_description': f'Удаление шаблона промпта {template.name}',
    })


# Безопасный импорт функции тестирования промптов
from Asistent.Test_Promot import prompt_template_test


# Dashboard метрик AI-ассистента
@staff_member_required
def ai_dashboard(request):
    """Dashboard метрик AI-ассистента"""
    from .analytics import AIMetricsDashboard
    
    # Создаем экземпляр dashboard
    dashboard = AIMetricsDashboard()
    
    # Получаем период для трендов (по умолчанию 30 дней)
    period_days = int(request.GET.get('period', 30))
    
    # Собираем все метрики
    context = {
        'daily_stats': dashboard.get_daily_stats(),
        'quality_metrics': dashboard.get_quality_metrics(),
        'ai_vs_human': dashboard.compare_ai_vs_human(),
        'schedule_performance': dashboard.get_schedule_performance(),
        'cost_analysis': dashboard.get_cost_analysis(),
        'trends': dashboard.get_trends(days=period_days),
        'period_days': period_days,
        'available_periods': [7, 14, 30, 60, 90],
        # SEO-метатеги
        'page_title': 'Dashboard AI-ассистента — IdealImage.ru',
        'page_description': 'Центральная панель управления AI-ассистентом: метрики производительности, качества контента и эффективности',
        'meta_keywords': 'AI dashboard, метрики AI, управление AI, AI-ассистент',
        'og_title': 'Dashboard AI-ассистента',
        'og_description': 'Центральная панель управления AI-ассистентом на IdealImage.ru',
    }
    
    return render(request, 'Asistent/dashboard.html', context)


# ============================================================================
# AI-ЧАТ VIEWS
# ============================================================================

# AI-Чат
@staff_member_required
def ai_chat_view(request):
    """Интерфейс AI-чата"""
    from .models import AIConversation, AIMessage
    
    # Получаем все диалоги пользователя
    conversations = AIConversation.objects.filter(
        admin=request.user,
        is_active=True
    ).order_by('-updated_at')
    
    # Получаем активный диалог
    conversation_id = request.GET.get('conversation')
    active_conversation = None
    chat_messages = []
    
    if conversation_id:
        try:
            active_conversation = AIConversation.objects.get(
                id=conversation_id,
                admin=request.user
            )
            chat_messages = active_conversation.messages.order_by('timestamp')
        except AIConversation.DoesNotExist:
            pass
    
    # Категории базы знаний
    from .models import AIKnowledgeBase
    categories = AIKnowledgeBase.CATEGORY_CHOICES
    
    # Очищаем Django messages для этой страницы, чтобы избежать дублирования
    django_messages = list(messages.get_messages(request))
    messages.get_messages(request).used = True  # Помечаем сообщения как использованные
    
    context = {
        'conversations': conversations,
        'active_conversation': active_conversation,
        'chat_messages': chat_messages,  # Используем уникальное имя, чтобы избежать конфликта с Django messages
        'categories': categories,
        # SEO мета-теги
        'page_title': 'AI-Чат — Управление сайтом IdealImage.ru',
        'page_description': 'Интерфейс AI-чата для управления сайтом через искусственный интеллект',
        'canonical_url': request.build_absolute_uri(),
        'og_title': 'AI-Чат — IdealImage.ru',
        'og_description': 'Интерактивный AI-ассистент для управления контентом',
        'og_image': request.build_absolute_uri('/static/images/ai-chat-preview.png'),
    }
    
    return render(request, 'Asistent/ai_chat.html', context)


# API: Создание нового диалога
@login_required
def get_prompt_variables(request, prompt_id):
    """API: Получить список переменных из промпта для автоподгрузки в расписание"""
    try:
        from .models import PromptTemplate

        prompt = PromptTemplate.objects.get(id=prompt_id)
        
        # Возвращаем переменные и дополнительную информацию
        return JsonResponse({
            'success': True,
            'variables': prompt.variables if isinstance(prompt.variables, list) else [],
            'name': prompt.name,
            'category': prompt.category,
            'blog_category_id': prompt.blog_category.id if prompt.blog_category else None,
            'blog_category_name': prompt.blog_category.title if prompt.blog_category else None
        })
    except PromptTemplate.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Промпт не найден'
        }, status=404)
    except Exception as e:
        logger.error(f"Ошибка get_prompt_variables: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# Dashboard аналитики AI vs Авторы
@staff_member_required
def ai_analytics_dashboard(request):
    """Dashboard аналитики AI vs Авторы"""
    from .analytics import get_analytics_data
    
    # Получаем период из GET параметра (по умолчанию 30 дней)
    period_days = int(request.GET.get('period', 30))
    
    # Загружаем аналитические данные
    analytics_data = get_analytics_data(period_days)
    
    context = {
        'analytics': analytics_data,
        'period_days': period_days,
        'available_periods': [7, 14, 30, 60, 90],
        # SEO-метатеги
        'page_title': f'Аналитика AI-ассистента ({period_days} дней) — IdealImage.ru',
        'page_description': 'Подробная аналитика работы AI-ассистента: статистика генерации статей, сравнение с авторами, производительность и эффективность',
        'meta_keywords': 'AI аналитика, статистика AI, AI vs авторы, производительность AI, метрики контента',
        'og_title': f'Аналитика AI-ассистента ({period_days} дней)',
        'og_description': 'Подробная аналитика работы AI-ассистента на IdealImage.ru',
    }
    
    return render(request, 'Asistent/ai_analytics_dashboard.html', context)


# Dashboard метрик AI-ассистента
@staff_member_required
def ai_dashboard(request):
    """Dashboard метрик AI-ассистента"""
    from .analytics import AIMetricsDashboard
    
    # Создаем экземпляр dashboard
    dashboard = AIMetricsDashboard()
    
    # Получаем период для трендов (по умолчанию 30 дней)
    period_days = int(request.GET.get('period', 30))
    
    # Собираем все метрики
    context = {
        'daily_stats': dashboard.get_daily_stats(),
        'quality_metrics': dashboard.get_quality_metrics(),
        'ai_vs_human': dashboard.compare_ai_vs_human(),
        'schedule_performance': dashboard.get_schedule_performance(),
        'cost_analysis': dashboard.get_cost_analysis(),
        'trends': dashboard.get_trends(days=period_days),
        'period_days': period_days,
        'available_periods': [7, 14, 30, 60, 90],
        # SEO-метатеги
        'page_title': 'Dashboard AI-ассистента — IdealImage.ru',
        'page_description': 'Центральная панель управления AI-ассистентом: метрики производительности, качества контента и эффективности',
        'meta_keywords': 'AI dashboard, метрики AI, управление AI, AI-ассистент',
        'og_title': 'Dashboard AI-ассистента',
        'og_description': 'Центральная панель управления AI-ассистентом на IdealImage.ru',
    }
    
    return render(request, 'Asistent/dashboard.html', context)


# ============================================================================
# AI-ЧАТ VIEWS
# ============================================================================

# AI-Чат
@staff_member_required
def ai_chat_view(request):
    """Интерфейс AI-чата"""
    from .models import AIConversation, AIMessage
    
    # Получаем все диалоги пользователя
    conversations = AIConversation.objects.filter(
        admin=request.user,
        is_active=True
    ).order_by('-updated_at')
    
    # Получаем активный диалог
    conversation_id = request.GET.get('conversation')
    active_conversation = None
    chat_messages = []
    
    if conversation_id:
        try:
            active_conversation = AIConversation.objects.get(
                id=conversation_id,
                admin=request.user
            )
            chat_messages = active_conversation.messages.order_by('timestamp')
        except AIConversation.DoesNotExist:
            pass
    
    # Категории базы знаний
    from .models import AIKnowledgeBase
    categories = AIKnowledgeBase.CATEGORY_CHOICES
    
    # Очищаем Django messages для этой страницы, чтобы избежать дублирования
    django_messages = list(messages.get_messages(request))
    messages.get_messages(request).used = True  # Помечаем сообщения как использованные
    
    context = {
        'conversations': conversations,
        'active_conversation': active_conversation,
        'chat_messages': chat_messages,  # Используем уникальное имя, чтобы избежать конфликта с Django messages
        'categories': categories,
        # SEO мета-теги
        'page_title': 'AI-Чат — Управление сайтом IdealImage.ru',
        'page_description': 'Интерфейс AI-чата для управления сайтом через искусственный интеллект',
        'canonical_url': request.build_absolute_uri(),
        'og_title': 'AI-Чат — IdealImage.ru',
        'og_description': 'Интерактивный AI-ассистент для управления контентом',
        'og_image': request.build_absolute_uri('/static/images/ai-chat-preview.png'),
    }
    
    return render(request, 'Asistent/ai_chat.html', context)


# API: Создание нового диалога
@staff_member_required
@require_POST
def api_create_conversation(request):
    """API: Создание нового диалога"""
    from .models import AIConversation, AIMessage
    import json
    
    try:
        title = request.POST.get('title', 'Новый диалог')
        initial_message = request.POST.get('initial_message', '')
        
        # Создаем диалог
        conversation = AIConversation.objects.create(
            admin=request.user,
            title=title
        )
        
        # Добавляем приветственное сообщение
        if initial_message:
            AIMessage.objects.create(
                conversation=conversation,
                role='assistant',
                content=initial_message
            )
        
        return JsonResponse({
            'success': True,
            'conversation_id': conversation.id,
            'title': conversation.title
        })
    
    except Exception as e:
        logger.error(f"Ошибка создания диалога: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# API: Отправка сообщения в чат
@staff_member_required
@require_POST
def api_chat_send(request):
    """API: Отправка сообщения в чат"""
    from .models import AIConversation, AIMessage
    from .ai_agent import AIAgent
    import json
    
    try:
        conversation_id = request.POST.get('conversation_id')
        message_text = request.POST.get('message', '').strip()
        
        if not message_text:
            return JsonResponse({
                'success': False,
                'error': 'Сообщение не может быть пустым'
            }, status=400)
        
        # Получаем диалог
        conversation = AIConversation.objects.get(
            id=conversation_id,
            admin=request.user
        )
        
        # Сохраняем сообщение администратора
        AIMessage.objects.create(
            conversation=conversation,
            role='admin',
            content=message_text
        )
        
        # Обрабатываем через AI-агента
        agent = AIAgent()
        result = agent.process_message(request.user, message_text, conversation)
        
        # Сохраняем ответ AI
        ai_message = AIMessage.objects.create(
            conversation=conversation,
            role='assistant',
            content=result.get('response', 'Ошибка обработки'),
            metadata={
                'task_created': result.get('task_created', False),
                'task_id': result.get('task_id'),
                'task_type': result.get('task_type')
            }
        )
        
        # Обновляем время диалога
        conversation.save()  # Обновит updated_at
        
        return JsonResponse({
            'success': True,
            'response': result.get('response'),
            'message_id': ai_message.id,
            'metadata': ai_message.metadata
        })
    
    except AIConversation.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Диалог не найден'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# API: Удаление диалога
@staff_member_required
@require_POST
def api_delete_conversation(request, conversation_id):
    """API: Удаление диалога"""
    from .models import AIConversation
    
    try:
        conversation = AIConversation.objects.get(
            id=conversation_id,
            admin=request.user
        )
        
        conversation.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Диалог удален'
        })
    
    except AIConversation.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Диалог не найден'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Ошибка удаления диалога: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# API: Поиск в базе знаний
@staff_member_required
def api_knowledge_search(request):
    """API: Поиск в базе знаний"""
    from .models import AIKnowledgeBase
    
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    
    knowledge = AIKnowledgeBase.objects.filter(is_active=True)
    
    if category:
        knowledge = knowledge.filter(category=category)
    
    if query:
        from django.db.models import Q
        knowledge = knowledge.filter(
            Q(title__icontains=query) | 
            Q(content__icontains=query) |
            Q(tags__contains=query)
        )
    
    knowledge = knowledge.order_by('-usage_count')[:20]
    
    results = [{
        'id': k.id,
        'category': k.category,
        'title': k.title,
        'content': k.content[:200] + '...' if len(k.content) > 200 else k.content,
        'usage_count': k.usage_count
    } for k in knowledge]
    
    return JsonResponse({
        'success': True,
        'results': results,
        'count': len(results)
    })

# API: Счетчики по категориям
@staff_member_required
def api_knowledge_counts(request):
    """API: Счетчики по категориям"""
    from .models import AIKnowledgeBase
    
    counts = {}
    for category, display in AIKnowledgeBase.CATEGORY_CHOICES:
        count = AIKnowledgeBase.objects.filter(
            category=category,
            is_active=True
        ).count()
        counts[category] = count
    
    return JsonResponse({
        'success': True,
        'counts': counts
    })

# API: Список записей категории
@staff_member_required
def api_knowledge_list(request, category):
    """API: Список записей категории"""
    from .models import AIKnowledgeBase
    from urllib.parse import unquote
    
    # Декодируем кириллицу из URL
    category_decoded = unquote(category)
    
    logger.info(f"📂 api_knowledge_list: category='{category}' → decoded='{category_decoded}'")
    
    items = AIKnowledgeBase.objects.filter(
        category=category_decoded,
        is_active=True
    ).order_by('-priority', '-usage_count')[:20]
    
    logger.info(f"  Найдено записей: {items.count()}")
    
    return JsonResponse({
        'success': True,
        'items': [{
            'id': k.id,
            'title': k.title,
            'content': k.content[:100] + '...' if len(k.content) > 100 else k.content,
            'priority': k.priority,
            'usage_count': k.usage_count
        } for k in items]
    })

# API: Получить одну запись по ID
@staff_member_required
def api_knowledge_get(request, knowledge_id):
    """API: Получить одну запись по ID"""
    from .models import AIKnowledgeBase
    
    try:
        item = AIKnowledgeBase.objects.get(id=knowledge_id)
        return JsonResponse({
            'success': True,
            'item': {
                'id': item.id,
                'category': item.category,
                'category_display': item.get_category_display(),
                'title': item.title,
                'content': item.content,
                'tags': item.tags if isinstance(item.tags, list) else [],
                'priority': item.priority,
                'is_active': item.is_active,
                'usage_count': item.usage_count,
                'created_at': item.created_at.isoformat(),
                'updated_at': item.updated_at.isoformat()
            }
        })
    except AIKnowledgeBase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Запись не найдена'
        }, status=404)
    except Exception as e:
        logger.error(f"Ошибка получения записи {knowledge_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# API: Создать новую запись в базе знаний
@staff_member_required
@require_POST
def api_knowledge_create(request):
    """API: Создать новую запись в базе знаний"""
    from .models import AIKnowledgeBase
    import json
    
    try:
        data = json.loads(request.body)
        
        # Валидация обязательных полей
        if not data.get('title') or not data.get('content'):
            return JsonResponse({
                'success': False,
                'error': 'Заголовок и содержание обязательны'
            }, status=400)
        
        # Создаём запись
        item = AIKnowledgeBase.objects.create(
            category=data.get('category', 'правила'),
            title=data['title'][:300],
            content=data['content'],
            tags=data.get('tags', []),
            priority=int(data.get('priority', 50)),
            is_active=data.get('is_active', True),
            created_by=request.user
        )
        
        logger.info(f"✅ Создана запись в базе знаний: #{item.id} - {item.title}")
        
        return JsonResponse({
            'success': True,
            'id': item.id,
            'message': 'Запись успешно создана'
        })
        
    except Exception as e:
        logger.error(f"Ошибка создания записи: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# API: Обновить существующую запись
@staff_member_required
@require_POST
def api_knowledge_update(request, knowledge_id):
    """API: Обновить существующую запись"""
    from .models import AIKnowledgeBase
    import json
    
    try:
        item = AIKnowledgeBase.objects.get(id=knowledge_id)
        data = json.loads(request.body)
        
        # Обновляем поля
        if 'category' in data:
            item.category = data['category']
        if 'title' in data:
            item.title = data['title'][:300]
        if 'content' in data:
            item.content = data['content']
        if 'tags' in data:
            item.tags = data['tags']
        if 'priority' in data:
            item.priority = int(data['priority'])
        if 'is_active' in data:
            item.is_active = data['is_active']
        
        item.save()
        
        logger.info(f"✅ Обновлена запись #{item.id} - {item.title}")
        
        return JsonResponse({
            'success': True,
            'message': 'Запись успешно обновлена'
        })
        
    except AIKnowledgeBase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Запись не найдена'
        }, status=404)
    except Exception as e:
        logger.error(f"Ошибка обновления записи {knowledge_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# API: Удалить запись из базы знаний
@staff_member_required
@require_POST
def api_knowledge_delete(request, knowledge_id):
    """API: Удалить запись из базы знаний"""
    from .models import AIKnowledgeBase
    
    try:
        item = AIKnowledgeBase.objects.get(id=knowledge_id)
        title = item.title
        item.delete()
        
        logger.info(f"✅ Удалена запись #{knowledge_id} - {title}")
        
        return JsonResponse({
            'success': True,
            'message': 'Запись успешно удалена'
        })
        
    except AIKnowledgeBase.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Запись не найдена'
        }, status=404)
    except Exception as e:
        logger.error(f"Ошибка удаления записи {knowledge_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# =====================================================
# ЧАТ-БОТ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ
# ПЕРЕНЕСЕНО В Asistent.ChatBot_AI.views
# =====================================================
# Все функции чат-бота перенесены в модуль ChatBot_AI
# - chatbot_message() -> ChatBot_AI.views.chatbot_message()
# - contact_admin_from_chat() -> ChatBot_AI.views.contact_admin_from_chat()
# - get_chatbot_settings_api() -> ChatBot_AI.views.get_chatbot_settings_api()
# - search_in_faq() -> ChatBot_AI.services.FAQSearchService
# - search_articles_by_query() -> ChatBot_AI.services.ArticleSearchService
# - format_articles_response() -> ChatBot_AI.services.ResponseFormatter


# ==================== УПРАВЛЕНИЕ ЗАДАЧАМИ DJANGO-Q ====================
# Страница активных задач Django-Q (выполняются сейчас)
@staff_member_required
def djangoq_tasks_active(request):
    """Страница активных задач Django-Q (выполняются сейчас)"""
    _lookup_legacy_djangoq_model('OrmQ', 'djangoq_tasks_active')
    active_results = TaskResult.objects.filter(status='STARTED').order_by('-date_started')
    active_tasks = [_to_legacy_task_view(item) for item in active_results]
    
    return render(request, 'Asistent/djangoq_tasks.html', {
        'tasks': active_tasks,
        'task_type': 'active',
        'title': '⚡ Активные задачи (Выполняются)',
        'description': 'Задачи, которые выполняются в данный момент',
        'show_actions': False,  # Активные задачи нельзя удалять/запускать
        'page_title': 'Активные задачи Celery - IdealImage.ru',
        'page_description': 'Список активных задач Celery, выполняющихся в данный момент',
    })

# Страница задач в очереди Django-Q
@staff_member_required
def djangoq_tasks_queued(request):
    """Страница задач в очереди"""
    _lookup_legacy_djangoq_model('OrmQ', 'djangoq_tasks_queued')
    queued_results = TaskResult.objects.filter(status='PENDING').order_by('date_created')
    queued_tasks = [_to_legacy_task_view(item) for item in queued_results]
    
    return render(request, 'Asistent/djangoq_tasks.html', {
        'tasks': queued_tasks,
        'task_type': 'queued',
        'title': '📋 Задачи в очереди',
        'description': 'Задачи, ожидающие выполнения',
        'show_actions': True,  # Задачи в очереди можно запускать/удалять
        'page_title': 'Задачи в очереди Celery - IdealImage.ru',
        'page_description': 'Список задач Celery, ожидающих выполнения',
    })

# Страница задач выполненных за последний час
@staff_member_required
def djangoq_tasks_recent(request):
    """Страница задач выполненных за последний час"""
    from datetime import timedelta

    _lookup_legacy_djangoq_model('Success', 'djangoq_tasks_recent')
    hour_ago = timezone.now() - timedelta(hours=1)
    recent_results = TaskResult.objects.filter(
        status='SUCCESS',
        date_done__gte=hour_ago,
    ).order_by('-date_done')
    recent_tasks = [_to_legacy_task_view(item) for item in recent_results]
    
    return render(request, 'Asistent/djangoq_tasks.html', {
        'tasks': recent_tasks,
        'task_type': 'recent',
        'title': '✅ Задачи за последний час',
        'description': 'Успешно выполненные задачи за последний час',
        'show_actions': False,  # Выполненные задачи только для просмотра
        'page_title': 'Задачи за час Celery - IdealImage.ru',
        'page_description': 'Успешно выполненные задачи Celery за последний час',
    })

# Страница всех задач Django-Q с фильтрацией и сортировкой
@staff_member_required
def djangoq_tasks_all(request):
    """Страница всех задач Django-Q с фильтрацией и сортировкой"""
    from django.core.paginator import Paginator
    
    _lookup_legacy_djangoq_model('Success', 'djangoq_tasks_all')
    _lookup_legacy_djangoq_model('Failure', 'djangoq_tasks_all')

    # Получаем параметры фильтрации и сортировки
    filter_type = request.GET.get('type', 'success')  # success, failed
    sort_by = request.GET.get('sort', '-stopped')  # -stopped, stopped, func, -time_taken, time_taken
    view_mode = request.GET.get('view', 'grid')  # grid, table
    search_query = request.GET.get('search', '').strip()
    
    # Получаем Celery результаты задач
    if filter_type == 'failed':
        task_results = TaskResult.objects.filter(status='FAILURE')
    else:
        task_results = TaskResult.objects.filter(status='SUCCESS')
    
    # Применяем поиск
    if search_query:
        task_results = task_results.filter(
            Q(task_name__icontains=search_query) |
            Q(task_kwargs__icontains=search_query) |
            Q(worker__icontains=search_query)
        )
    
    valid_sorts = {
        '-stopped': '-date_done',
        'stopped': 'date_done',
        'func': 'task_name',
        '-func': '-task_name',
        'group': 'worker',
        '-group': '-worker',
    }

    if sort_by in ['-time_taken', 'time_taken']:
        task_results = task_results.annotate(
            execution_time=ExpressionWrapper(
                F('date_done') - F('date_started'),
                output_field=DurationField(),
            )
        ).order_by('-execution_time' if sort_by == '-time_taken' else 'execution_time')
    else:
        task_results = task_results.order_by(valid_sorts.get(sort_by, '-date_done'))

    tasks_list = [_to_legacy_task_view(item) for item in task_results]
    
    # Пагинация
    per_page = 50 if view_mode == 'grid' else 100
    paginator = Paginator(tasks_list, per_page)
    page = request.GET.get('page', 1)
    tasks_page = paginator.get_page(page)
    
    return render(request, 'Asistent/djangoq_tasks.html', {
        'tasks': tasks_page,
        'task_type': 'all',
        'title': '📊 Все задачи Celery',
        'description': 'История выполнения всех задач',
        'filter_type': filter_type,
        'sort_by': sort_by,
        'view_mode': view_mode,
        'search_query': search_query,
        'show_actions': False,
        'show_pagination': True,
        'page_title': 'Все задачи Celery - IdealImage.ru',
        'page_description': 'Полная история выполнения задач Celery с фильтрацией',
    })

# Мгновенный запуск задачи из очереди
@staff_member_required
@require_POST
def djangoq_task_run_now(request, task_id):
    """Мгновенный запуск задачи из очереди"""
    from Asistent.tasks import async_task

    try:
        task_result = get_object_or_404(TaskResult, task_id=task_id)
        task_name = task_result.task_name or 'Unnamed task'
        task_args = _safe_parse_payload(task_result.task_args, [])
        task_kwargs = _safe_parse_payload(task_result.task_kwargs, {})
        if not isinstance(task_args, (list, tuple)):
            task_args = [task_args]
        if not isinstance(task_kwargs, dict):
            task_kwargs = {}

        async_task(
            task_name,
            *task_args,
            **task_kwargs,
            task_name=f'manual:{task_name}'
        )
        
        messages.success(request, f'✅ Задача "{task_name}" запущена немедленно!')
        logger.info(f"Задача {task_name} (ID: {task_id}) запущена вручную")
        
        return redirect('asistent:djangoq_tasks_queued')
        
    except Exception as e:
        messages.error(request, f'❌ Ошибка запуска задачи: {str(e)}')
        logger.error(f"Ошибка запуска задачи {task_id}: {e}")
        return redirect('asistent:djangoq_tasks_queued')


# Удаление задачи из очереди
@staff_member_required
@require_POST
def djangoq_task_delete(request, task_id):
    """Удаление задачи из очереди"""

    try:
        task_result = TaskResult.objects.filter(task_id=task_id).first()
        task_name = (task_result.task_name if task_result else '') or 'Unnamed task'

        AsyncResult(task_id).revoke(terminate=False)
        if task_result:
            task_result.status = 'REVOKED'
            task_result.save(update_fields=['status'])
        
        messages.success(request, f'✅ Задача "{task_name}" удалена из очереди')
        logger.info(f"Задача {task_name} (ID: {task_id}) удалена из очереди")
        
        return redirect(request.META.get('HTTP_REFERER', 'asistent:djangoq_tasks_queued'))
        
    except Exception as e:
        messages.error(request, f'❌ Ошибка удаления задачи: {str(e)}')
        logger.error(f"Ошибка удаления задачи {task_id}: {e}")
        return redirect('asistent:djangoq_tasks_queued')

# Страница создания новой задачи Django-Q
@staff_member_required
def djangoq_task_create(request):
    """Страница создания новой задачи Django-Q"""
    if request.method == 'POST':
        from Asistent.tasks import async_task
        
        func_name = request.POST.get('func_name')
        task_name = request.POST.get('task_name')
        schedule_type = request.POST.get('schedule_type', 'once')  # once, schedule
        
        try:
            if schedule_type == 'once':
                # Одноразовая задача
                async_task(func_name, task_name=task_name)
                messages.success(request, f'✅ Задача "{task_name}" добавлена в очередь!')
                logger.info(f"Создана одноразовая задача: {task_name}")
                return redirect('asistent:djangoq_tasks_queued')
            else:
                # Создаем расписание
                minutes = int(request.POST.get('minutes', 60))

                interval, _ = IntervalSchedule.objects.get_or_create(
                    every=max(1, minutes),
                    period=IntervalSchedule.MINUTES,
                )

                PeriodicTask.objects.create(
                    name=task_name,
                    task=func_name,
                    interval=interval,
                    enabled=True,
                )
                messages.success(request, f'✅ Расписание "{task_name}" создано! Запуск каждые {minutes} минут.')
                logger.info(f"Создано расписание: {task_name} (каждые {minutes} мин)")
                return redirect('asistent:ai_schedules')
            
        except Exception as e:
            messages.error(request, f'❌ Ошибка создания задачи: {e}')
            logger.error(f"Ошибка создания задачи: {e}")
    
    # Список доступных функций для выполнения
    available_functions = [
        {'value': 'Asistent.tasks.monitor_djangoq_cluster', 'label': '🔍 Мониторинг Django-Q кластера'},
        {'value': 'Asistent.tasks.moderate_article_task', 'label': '✍️ Модерация статьи'},
        {'value': 'Asistent.tasks.generate_ai_article', 'label': '🤖 Генерация AI-статьи'},
        {'value': 'Asistent.tasks.process_scheduled_generation', 'label': '📅 Обработка расписания генерации'},
    ]
    
    return render(request, 'Asistent/djangoq_task_create.html', {
        'available_functions': available_functions,
        'title': '➕ Создать задачу Celery',
        'page_title': 'Создать задачу Celery - IdealImage.ru',
        'page_description': 'Создание новой задачи Celery для выполнения',
    })

# Детальная информация о задаче
@staff_member_required
def djangoq_task_detail(request, task_id, task_type):
    """Детальная информация о задаче"""
    task_result = TaskResult.objects.filter(task_id=task_id).first()
    if not task_result:
        legacy_ormq = _lookup_legacy_djangoq_model('OrmQ', 'djangoq_task_detail')
        if legacy_ormq:
            # LEGACY django_q 2026 migration
            _warn_legacy_queue('djangoq_task_detail:empty_queryset_returned')
        raise Http404("Задача не найдена")

    task = _to_legacy_task_view(task_result)

    if task_result.status in ('PENDING', 'STARTED'):
        model_name = 'OrmQ'
        task_type = 'active' if task_result.status == 'STARTED' else 'queued'
    elif task_result.status == 'FAILURE':
        model_name = 'Failure'
        task_type = 'failed'
    else:
        model_name = 'Success'
        task_type = 'success'
    
    return render(request, 'Asistent/djangoq_task_detail.html', {
        'task': task,
        'task_type': task_type,
        'model_name': model_name,
        'title': f'Детали задачи',
        'page_title': f'Детали задачи Celery - IdealImage.ru',
        'page_description': f'Подробная информация о задаче Celery',
    })


# ==================== УПРАВЛЕНИЕ ЗАДАНИЯМИ АВТОРОВ (CONTENT TASK) ====================
# Доступные задания авторов
@staff_member_required
def content_tasks_available(request):
    """Доступные задания авторов"""
    tasks = ContentTask.objects.filter(status='available').select_related('category', 'created_by').order_by('-created_at')
    
    return render(request, 'Asistent/content_tasks.html', {
        'tasks': tasks,
        'task_status': 'available',
        'title': '📋 Доступные задания',
        'description': 'Задания, доступные для выполнения авторами',
        'show_actions': True,
        'page_title': 'Доступные задания - IdealImage.ru',
        'page_description': 'Список доступных заданий для авторов',
    })


# Задания в работе
@staff_member_required
def content_tasks_active(request):
    """Задания в работе"""
    from .models import TaskAssignment
    
    assignments = TaskAssignment.objects.filter(
        status='in_progress'
    ).select_related('task', 'task__category', 'author', 'author__profile').order_by('-taken_at')
    
    return render(request, 'Asistent/content_tasks.html', {
        'assignments': assignments,
        'task_status': 'active',
        'title': '🔄 Задания в работе',
        'description': 'Задания, которые выполняются авторами сейчас',
        'show_actions': True,
        'page_title': 'Задания в работе - IdealImage.ru',
        'page_description': 'Список заданий в работе',
    })

# Выполненные задания за неделю
@staff_member_required
def content_tasks_completed(request):
    """Выполненные задания за неделю"""
    from .models import TaskAssignment
    from datetime import timedelta
    
    week_ago = timezone.now() - timedelta(days=7)
    assignments = TaskAssignment.objects.filter(
        status__in=['completed', 'approved'],
        completed_at__gte=week_ago
    ).select_related('task', 'task__category', 'author', 'author__profile', 'article').order_by('-completed_at')
    
    # Статистика по авторам
    from django.db.models import Count
    author_stats = TaskAssignment.objects.filter(
        status__in=['completed', 'approved'],
        completed_at__gte=week_ago
    ).values('author__username', 'author__id').annotate(
        completed_count=Count('id')
    ).order_by('-completed_count')
    
    return render(request, 'Asistent/content_tasks.html', {
        'assignments': assignments,
        'task_status': 'completed',
        'title': '✅ Выполненные задания (неделя)',
        'description': 'Задания, выполненные за последнюю неделю',
        'show_actions': False,
        'author_stats': author_stats,
        'page_title': 'Выполненные задания - IdealImage.ru',
        'page_description': 'Список выполненных заданий за неделю',
    })

# Детали задания с назначениями и связью с Django-Q
@staff_member_required
def content_task_detail(request, task_id):
    """Детали задания с назначениями и связью с Django-Q"""
    from .models import TaskAssignment
    
    task = get_object_or_404(ContentTask, id=task_id)
    assignments = TaskAssignment.objects.filter(task=task).select_related('author', 'author__profile', 'article')
    
    # Ищем связанные Celery-задачи (LEGACY django_q 2026 migration)
    related_djangoq_tasks = []
    
    celery_success = TaskResult.objects.filter(
        status='SUCCESS',
        task_name__icontains=task.title,
    ).order_by('-date_done')[:5]
    
    # Поиск в pending задачах по kwargs.task_id
    djangoq_queued = []
    try:
        queued_tasks = TaskResult.objects.filter(status__in=['PENDING', 'STARTED']).order_by('-date_created')[:50]
        for q_task in queued_tasks:
            task_kwargs = _safe_parse_payload(q_task.task_kwargs, {})
            if not isinstance(task_kwargs, dict):
                task_kwargs = {}
            if task_kwargs.get('task_id') == task.id:
                djangoq_queued.append(_to_legacy_task_view(q_task))
            if len(djangoq_queued) >= 5:
                break
    except Exception as e:
        logger.error(f"Ошибка поиска связанных Django-Q задач: {e}")
    
    related_djangoq_tasks = [_to_legacy_task_view(item) for item in celery_success] + djangoq_queued
    
    return render(request, 'Asistent/content_task_detail.html', {
        'task': task,
        'assignments': assignments,
        'related_djangoq_tasks': related_djangoq_tasks,
        'title': f'Задание: {task.title}',
        'page_title': f'{task.title} - IdealImage.ru',
        'page_description': f'Детали задания для авторов: {task.title}',
    })


# ==================== УПРАВЛЕНИЕ РАСПИСАНИЯМИ AI ====================
# Активные расписания AI
@staff_member_required
def ai_schedules_active(request):
    """Активные расписания AI"""
    schedules = AISchedule.objects.filter(is_active=True).select_related('category').order_by('-last_run')
    
    return render(request, 'Asistent/ai_schedules_list.html', {
        'schedules': schedules,
        'schedule_status': 'active',
        'title': '🤖 Активные расписания AI',
        'description': 'Расписания, которые генерируют контент автоматически',
        'page_title': 'Активные расписания AI - IdealImage.ru',
        'page_description': 'Список активных расписаний AI-генерации',
    })


# Неактивные расписания AI
@staff_member_required
def ai_schedules_inactive(request):
    """Неактивные расписания AI"""
    schedules = AISchedule.objects.filter(is_active=False).select_related('category').order_by('-created_at')
    
    return render(request, 'Asistent/ai_schedules_list.html', {
        'schedules': schedules,
        'schedule_status': 'inactive',
        'title': '⏸️ Неактивные расписания AI',
        'description': 'Расписания, которые приостановлены',
        'page_title': 'Неактивные расписания AI - IdealImage.ru',
        'page_description': 'Список неактивных расписаний AI-генерации',
    })

# Статистика генераций AI за сегодня
@staff_member_required
def ai_schedules_stats_today(request):
    """Статистика генераций AI за сегодня"""
    from blog.models import Post
    from datetime import timedelta
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Статьи AI за сегодня
    ai_posts_today = Post.objects.filter(
        author__username='AI',
        created__gte=today_start
    ).select_related('category').order_by('-created')
    
    # Статистика по расписаниям
    schedules_stats = []
    for schedule in AISchedule.objects.filter(is_active=True).select_related('category'):
        posts_count = Post.objects.filter(
            author__username='AI',
            category=schedule.category,
            created__gte=today_start
        ).count()
        
        schedules_stats.append({
            'schedule': schedule,
            'posts_today': posts_count
        })
    
    return render(request, 'Asistent/ai_schedules_list.html', {
        'ai_posts_today': ai_posts_today,
        'schedules_stats': schedules_stats,
        'schedule_status': 'stats',
        'title': '📊 Генерации AI сегодня',
        'description': f'Сгенерировано {ai_posts_today.count()} статей за сегодня',
        'page_title': 'Статистика AI сегодня - IdealImage.ru',
        'page_description': 'Статистика генераций AI за сегодня',
    })


# ============================================================================
# GIGACHAT МОНИТОРИНГ И УПРАВЛЕНИЕ
# ============================================================================
# API: Получить баланс токенов всех моделей GigaChat
@staff_member_required
def api_gigachat_balance(request):
    """API: Получить баланс токенов всех моделей GigaChat"""
    from .gigachat_api import get_gigachat_client, check_and_update_gigachat_balance
    from .models import GigaChatUsageStats
    
    try:
        balances = check_and_update_gigachat_balance()
        client = get_gigachat_client()
        
        # Получаем статистику из БД
        stats = GigaChatUsageStats.objects.all().values(
            'model_name', 'tokens_remaining', 'total_requests', 
            'successful_requests', 'failed_requests', 'last_check_at'
        )
        
        return JsonResponse({
            'status': 'ok',
            'balances': balances,
            'stats': list(stats),
            'current_model': client.settings.current_model,
            'check_after_requests': client.settings.check_balance_after_requests,
            'auto_switch_enabled': client.settings.auto_switch_enabled
        })
    except Exception as e:
        logger.error(f"Ошибка получения баланса GigaChat: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

# API: Обновить настройки GigaChat
@staff_member_required
@require_POST
def api_gigachat_settings_update(request):
    """API: Обновить настройки GigaChat"""
    from .models import GigaChatSettings
    
    try:
        settings = GigaChatSettings.objects.get(pk=1)
        
        check_after = request.POST.get('check_balance_after_requests')
        if check_after:
            settings.check_balance_after_requests = int(check_after)
        
        auto_switch = request.POST.get('auto_switch_enabled')
        if auto_switch is not None:
            settings.auto_switch_enabled = auto_switch == 'true'
        
        settings.save()
        
        logger.info(f"Настройки GigaChat обновлены: проверка после {settings.check_balance_after_requests} запросов, автопереключение: {settings.auto_switch_enabled}")
        
        return JsonResponse({
            'status': 'ok',
            'message': 'Настройки обновлены',
            'check_balance_after_requests': settings.check_balance_after_requests,
            'auto_switch_enabled': settings.auto_switch_enabled
        })
    except Exception as e:
        logger.error(f"Ошибка обновления настроек GigaChat: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

    recent_failed_runs = AIScheduleRun.objects.filter(status__in=['failed', 'partial']).order_by('-started_at')[:5]
    failed_last24 = AIScheduleRun.objects.filter(status='failed', started_at__gte=day_ago).count()

# Журнал запусков расписаний
@staff_member_required
def schedule_runs(request):
    status_filter = request.GET.get('status', '').strip()
    strategy_filter = request.GET.get('strategy', '').strip()
    schedule_query = request.GET.get('schedule', '').strip()
    date_from_raw = request.GET.get('date_from', '').strip()
    date_to_raw = request.GET.get('date_to', '').strip()
    per_page = int(request.GET.get('per_page', '25') or 25)

    runs_qs = AIScheduleRun.objects.select_related('schedule').order_by('-started_at')

    if status_filter:
        runs_qs = runs_qs.filter(status=status_filter)
    if strategy_filter:
        runs_qs = runs_qs.filter(strategy_type=strategy_filter)
    if schedule_query:
        runs_qs = runs_qs.filter(
            Q(schedule__name__icontains=schedule_query) |
            Q(schedule__id__iexact=schedule_query)
        )
    if date_from_raw:
        date_from = parse_date(date_from_raw)
        if date_from:
            runs_qs = runs_qs.filter(started_at__date__gte=date_from)
    if date_to_raw:
        date_to = parse_date(date_to_raw)
        if date_to:
            runs_qs = runs_qs.filter(started_at__date__lte=date_to)

    paginator = Paginator(runs_qs, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'strategy_filter': strategy_filter,
        'schedule_query': schedule_query,
        'date_from': date_from_raw,
        'date_to': date_to_raw,
        'per_page': per_page,
        'status_choices': AIScheduleRun.STATUS_CHOICES,
        'strategy_choices': AISchedule.STRATEGY_CHOICES,
        'page_title': 'Журнал запусков расписаний AI',
        'page_description': 'Мониторинг выполнения расписаний AI-системы',
        'title': 'Журнал запусков расписаний AI',
    }
    return render(request, 'Asistent/admin_schedule_runs.html', context)


@staff_member_required
def schedule_run_detail(request, run_id):
    run = get_object_or_404(AIScheduleRun.objects.select_related('schedule'), pk=run_id)
    context_snapshot = run.context_snapshot or {}
    result_payload = run.result_payload or {}
    errors = run.errors or []
    logs = context_snapshot.get('logs', [])

    data = {
        'id': run.id,
        'schedule': {
            'id': run.schedule.id,
            'name': run.schedule.name,
            'strategy_type': run.strategy_type,
        },
        'status': run.status,
        'created_count': run.created_count,
        'started_at': run.started_at.isoformat() if run.started_at else None,
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'duration_seconds': run.duration.total_seconds() if run.duration else None,
        'errors': errors,
        'result': result_payload,
        'context': {
            'current_step': context_snapshot.get('current_step'),
            'logs': logs,
            'results': context_snapshot.get('results', {}),
        },
    }
    return JsonResponse({'success': True, 'run': data})


# ============================================================================
# ПАРСИНГ ПОПУЛЯРНЫХ СТАТЕЙ
# ============================================================================

@staff_member_required
def parsed_articles_dashboard(request):
    """Дашборд для отображения спаршенных статей за сегодня."""
    from Asistent.parsers.models import ParsedArticle, ParsingCategory
    from blog.models import Category as BlogCategory
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Получаем параметры фильтрации
    category_filter = request.GET.get('category', '')
    source_filter = request.GET.get('source', '')
    status_filter = request.GET.get('status', 'pending')
    
    # Получаем спаршенные статьи за сегодня
    articles = ParsedArticle.objects.filter(parsed_at__gte=today_start)
    
    # Применяем фильтры
    if category_filter:
        articles = articles.filter(category_id=category_filter)
    
    if source_filter:
        articles = articles.filter(source_name__icontains=source_filter)
    
    if status_filter:
        articles = articles.filter(status=status_filter)
    
    # Группируем по категориям
    articles_by_category = {}
    for article in articles.order_by('-popularity_score', '-parsed_at'):
        cat_name = article.category.title if article.category else 'Без категории'
        if cat_name not in articles_by_category:
            articles_by_category[cat_name] = []
        articles_by_category[cat_name].append(article)
    
    # Статистика
    stats = {
        'total': articles.count(),
        'pending': articles.filter(status='pending').count(),
        'approved': articles.filter(status='approved').count(),
        'selected': articles.filter(selected_for_posting=True).count(),
        'published': articles.filter(status='published').count(),
    }
    
    # Категории для фильтра
    categories = BlogCategory.objects.all().order_by('title')
    
    context = {
        'articles_by_category': articles_by_category,
        'stats': stats,
        'categories': categories,
        'selected_category': category_filter,
        'selected_source': source_filter,
        'selected_status': status_filter,
        'page_title': 'Парсинг статей — IdealImage.ru',
        'page_description': 'Дашборд для модерации спаршенных статей',
    }
    
    return render(request, 'Asistent/parsed_articles_dashboard.html', context)


@staff_member_required
@require_POST
def api_parsed_articles_toggle_selection(request, article_id):
    """API: Переключить выбор статьи для публикации."""
    from Asistent.parsers.models import ParsedArticle
    
    try:
        article = get_object_or_404(ParsedArticle, id=article_id)
        article.selected_for_posting = not article.selected_for_posting
        article.save()
        
        return JsonResponse({
            'success': True,
            'selected': article.selected_for_posting
        })
    except Exception as e:
        logger.error(f"Ошибка переключения выбора статьи: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@staff_member_required
@require_POST
def api_parsed_articles_autopost(request):
    """API: Автопостинг выбранных статей."""
    from Asistent.parsers.autoposter import autopost_selected_articles
    
    try:
        results = autopost_selected_articles()
        
        return JsonResponse({
            'success': True,
            'results': results
        })
    except Exception as e:
        logger.error(f"Ошибка автопостинга: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)