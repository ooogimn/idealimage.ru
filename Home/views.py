from django.shortcuts import render, redirect
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q, F, Count, Sum
from django.views.generic import *
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.core.cache import cache
from decimal import Decimal
from Visitor.models import *
from blog.models import *
from .models import *
import logging

logger = logging.getLogger(__name__)


def get_active_landing():
    """Определяет активный лендинг из конфигурации"""
    try:
        config = LandingConfig.get_solo()
        return config.active_landing
    except:
        return 'landing1'


def home(request):
    """Главная страница - лендинг с категориями и статистикой (с кэшированием)"""
    # Проверяем активный лендинг
    active = get_active_landing()
    if active == 'landing2':
        return landing_2(request)
    
    from datetime import timedelta
    from django.utils import timezone
    from Home.models import LandingSection
    
    # Кэшируем фоны секций (обновляется раз в час)
    sections_backgrounds = cache.get('landing_sections_backgrounds')
    if sections_backgrounds is None:
        sections_backgrounds = {}
        for section in LandingSection.objects.filter(is_active=True):
            sections_backgrounds[section.section] = section.get_background_style()
        cache.set('landing_sections_backgrounds', sections_backgrounds, 3600)  # 1 час
    
    # Кэшируем статистику (обновляется раз в 10 минут)
    stats = cache.get('landing_stats')
    if stats is None:
        total_posts = Post.objects.filter(status='published').count()
        total_authors = Profile.objects.filter(is_author=True).count()
        total_comments = Comment.objects.count()
        stats = {
            'total_posts': total_posts,
            'total_authors': total_authors,
            'total_comments': total_comments,
            'monthly_visitors': '50K+',
        }
        cache.set('landing_stats', stats, 600)  # 10 минут
    
    # Оптимизированные запросы постов (только нужные поля + select_related)
    post_fields = ['id', 'title', 'slug', 'kartinka', 'views', 'created', 'category', 'author', 'video_url']
    
    # ВСЕ КАТЕГОРИИ с 3 самыми новыми статьями в каждой
    # Кэшируем на 10 минут для оптимизации
    categories_data = cache.get('home_categories_data')
    if categories_data is None:
        # Получаем все категории, у которых есть опубликованные статьи
        categories_with_posts = Category.objects.filter(
            posts__status='published'
        ).distinct().order_by('title')
        
        # Оптимизация: используем Prefetch для избежания N+1 проблемы
        from django.db.models import Prefetch
        
        # Создаем prefetch для постов каждой категории с аннотациями
        posts_prefetch = Prefetch(
            'posts',
            queryset=Post.objects.filter(
                status='published'
            ).only(*post_fields).select_related(
                'category', 
                'author__profile'
            ).annotate(
                likes_count=Count('likes', distinct=True),
                comments_count=Count('comments', filter=Q(comments__active=True), distinct=True)
            ).order_by('-created')[:6],
            to_attr='latest_posts'
        )
        
        # Получаем категории с prefetch
        categories_with_posts = categories_with_posts.prefetch_related(posts_prefetch)
        
        # Формируем данные
        categories_data = []
        for category in categories_with_posts:
            # Используем latest_posts из prefetch
            posts = getattr(category, 'latest_posts', [])
            
            # Добавляем только если есть статьи
            if posts:
                categories_data.append({
                    'category': category,
                    'posts': posts,
                    'title': category.title,
                })
        
        # Кэшируем на 10 минут
        cache.set('home_categories_data', categories_data, 600)
    
    # Последние опубликованные статьи (3 карточки)
    # Кэшируем на 5 минут для оптимизации
    # Сортировка по updated - показывает действительно последние опубликованные/обновлённые статьи
    latest_posts = cache.get('home_latest_posts')
    if latest_posts is None:
        latest_posts = Post.objects.filter(
            status='published'
        ).only(*post_fields).select_related(
            'category', 
            'author__profile'
        ).annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', filter=Q(comments__active=True), distinct=True)
        ).order_by('-updated')[:3]
        cache.set('home_latest_posts', list(latest_posts), 300)  # 5 минут
    
    # Топ 12 статей по просмотрам за всё время (кэшируем на 30 минут)
    top_posts = cache.get('landing_top_posts')
    if top_posts is None:
        # Берем топ 12 статей по просмотрам БЕЗ ограничения по дате
        # Оптимизация: используем аннотации вместо prefetch_related для likes/comments
        top_posts = Post.objects.filter(
            status='published'
        ).only(*post_fields).select_related(
            'category', 
            'author__profile'
        ).annotate(
            likes_count=Count('likes', distinct=True),
            comments_count=Count('comments', filter=Q(comments__active=True), distinct=True)
        ).order_by('-views')[:12]
        
        cache.set('landing_top_posts', list(top_posts), 1800)  # 30 минут
    
    # Порталы для секции "Сеть порталов" (кэшируем на 30 минут)
    portals = cache.get('home_portals')
    if portals is None:
        portals = Portal.objects.filter(is_active=True).order_by('order', 'name')[:8]
        cache.set('home_portals', list(portals), 1800)  # 30 минут
    
    # Кэшируем категории для меню (обновляется раз в 5 минут)
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)  # кэш на 5 минут
    
    # SEO метаданные
    page_title = 'IdealImage.ru - Ваш путеводитель в мире красоты с AI'
    page_description = 'Уникальный контент о моде, красоте и здоровье. AI-модерация и продвижение. Станьте блогером, зарабатывайте деньги, учитесь у AI!'
    
    # Текущая дата для виджета календаря (формат YYYYMMDD для обновления кэша)
    from datetime import datetime
    current_date = datetime.now().strftime('%Y%m%d')
    
    return render(request, 'home/index.html', {
        'page_title': page_title,
        'page_description': page_description,
        'categories_data': categories_data,  # Все категории с их статьями
        'latest_posts': latest_posts,
        'stats': stats,
        'top_posts': top_posts,
        'sections_backgrounds': sections_backgrounds,
        'portals': portals,
        'categorys': categorys,
        'current_date': current_date,  # Текущая дата для виджета календаря
    })



class SearchPageView(ListView):
    model = Post  
    template_name = 'home/search.html'
    paginate_by = 12
    
    def get_queryset(self):
        query = self.request.GET.get('query')
        if query:
            # Искать только среди опубликованных статей
            return Post.objects.filter(
                Q(title__icontains=query) | 
                Q(description__icontains=query) | 
                Q(content__icontains=query),
                status='published'
            ).select_related('author', 'category').prefetch_related('tags').order_by('-created')
        return Post.objects.none()
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('query')
        context['query'] = query
        
        # Добавляем категории для меню
        categorys = cache.get('categorys_list')
        if categorys is None:
            categorys = Category.objects.all()
            cache.set('categorys_list', categorys, 300)  # кэш на 5 минут
        context['categorys'] = categorys
        
        if query:
            context['page_title'] = f'Поиск: {query} - IdealImage.ru'
            context['page_description'] = f'Результаты поиска по запросу "{query}" на IdealImage.ru'
        else:
            context['page_title'] = 'Поиск статей - IdealImage.ru'
            context['page_description'] = 'Поиск статей по сайту IdealImage.ru'
        
        return context 


def documents(request):
    """Страница с юридическими документами"""
    # Категории для меню
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    
    page_title = 'Юридические документы - IdealImage.ru'
    page_description = 'Политика конфиденциальности, пользовательское соглашение и другие юридические документы сайта IdealImage.ru'
    return render(request, 'home/documents.html', {
        'page_title': page_title,
        'page_description': page_description,
        'categorys': categorys,
    })


def agreement(request):
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    page_title = 'Пользовательское соглашение - IdealImage.ru'
    page_description = 'Пользовательское соглашение, регулирующее использование сервиса Древо Жизни на сайте IdealImage.ru'
    return render(request, 'home/legal/agreement.html', {'page_title': page_title, 'page_description': page_description, 'categorys': categorys})


def privacy(request):
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    page_title = 'Политика обработки персональных данных - IdealImage.ru'
    page_description = 'Политика конфиденциальности и обработки персональных данных сайта IdealImage.ru'
    return render(request, 'home/legal/privacy.html', {'page_title': page_title, 'page_description': page_description, 'categorys': categorys})


def cookie_policy(request):
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    page_title = 'Политика использования cookie - IdealImage.ru'
    page_description = 'Политика использования файлов cookie сайтом IdealImage.ru'
    return render(request, 'home/legal/cookie_policy.html', {'page_title': page_title, 'page_description': page_description, 'categorys': categorys})


def offer(request):
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    page_title = 'Публичная оферта - IdealImage.ru'
    page_description = 'Официальная публичная оферта оказания услуг и использования сайта IdealImage.ru'
    return render(request, 'home/legal/offer.html', {'page_title': page_title, 'page_description': page_description, 'categorys': categorys})


def requisites(request):
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    page_title = 'Реквизиты и контакты - IdealImage.ru'
    page_description = 'Юридические реквизиты, контактная информация и способы связи с администрацией IdealImage.ru'
    return render(request, 'home/legal/requisites.html', {'page_title': page_title, 'page_description': page_description, 'categorys': categorys})


def help_page(request):
    """Страница помощи"""
    # Категории для меню
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    
    page_title = 'Помощь - IdealImage.ru'
    page_description = 'Часто задаваемые вопросы и помощь пользователям сайта IdealImage.ru'
    return render(request, 'home/help.html', {
        'page_title': page_title,
        'page_description': page_description,
        'categorys': categorys,
    })


def advertising(request):
    """Страница для рекламодателей"""
    # Категории для меню
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    
    page_title = 'Реклама на сайте - IdealImage.ru'
    page_description = 'Размещение рекламы на IdealImage.ru. Условия сотрудничества и контактная информация для рекламодателей'
    return render(request, 'home/advertising.html', {
        'page_title': page_title,
        'page_description': page_description,
        'categorys': categorys,
    })


def landing_2(request):
    """Лендинг №2 - Салон красоты"""
    # Используем существующие модели для контента
    
    # Услуги - берем категории (можно создать специальную категорию для услуг)
    services = Category.objects.all()[:6]
    
    # Мастера - авторы сайта
    masters = Profile.objects.filter(is_author=True)[:6]
    
    # Лучшие статьи блога - популярные посты с картинками
    # Оптимизированный запрос с prefetch для уменьшения количества запросов к БД
    portfolio = Post.objects.filter(
        status='published',
        kartinka__isnull=False
    ).select_related(
        'category',
        'author',
        'author__profile'
    ).prefetch_related(
        'comments',
        'likes'
    ).order_by('-views')[:6]
    
    # Отзывы - одобренные комментарии с высоким рейтингом
    testimonials = Comment.objects.filter(
        active=True
    ).select_related('post', 'author_comment').order_by('-created')[:6]
    
    # Кэшируем категории для меню (обновляется раз в 5 минут)
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)  # кэш на 5 минут
    
    # SEO
    page_title = 'IdealImage Beauty Studio - Салон красоты в Москве'
    page_description = 'Профессиональные услуги красоты: парикмахерские услуги, маникюр, педикюр, косметология, SPA и массаж. Запишитесь онлайн!'
    
    return render(request, 'home/landing2.html', {
        'page_title': page_title,
        'page_description': page_description,
        'services': services,
        'masters': masters,
        'portfolio': portfolio,
        'testimonials': testimonials,
        'categorys': categorys,
    })


@require_POST
def booking_submit(request):
    """AJAX обработка формы записи"""
    try:
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        service = request.POST.get('service', '').strip()
        address = request.POST.get('address', '').strip()
        
        # Валидация
        if not name or not phone:
            return JsonResponse({
                'success': False,
                'error': 'Пожалуйста, заполните обязательные поля'
            }, status=400)
        
        # Логирование заявки (можно сохранить в модель Comment с типом 'booking')
        logger.info(f'Новая заявка на запись: {name}, {phone}, {service}')
        
        # Можно отправить уведомление через пайплайн дистрибуции
        try:
            from Asistent.tasks import run_pipeline_by_slug_task

            payload = {
                "triggered_by": "booking_form",
                "message": (
                    "🔔 Новая заявка на запись!\n\n"
                    f"👤 Имя: {name}\n"
                    f"📞 Телефон: {phone}\n"
                    f"💅 Услуга: {service}"
                ),
            }
            if address:
                payload["message"] += f"\n📍 Адрес: {address}"

            run_pipeline_by_slug_task("distribution-flow", payload)
        except Exception:
            logger.exception("Не удалось отправить уведомление о бронировании")
        
        return JsonResponse({
            'success': True,
            'message': 'Спасибо! Ваша заявка принята. Мы свяжемся с вами в ближайшее время.'
        })
        
    except Exception as e:
        logger.error(f'Ошибка обработки заявки: {e}')
        return JsonResponse({
            'success': False,
            'error': 'Произошла ошибка. Пожалуйста, позвоните нам напрямую.'
        }, status=500)


def master_admin_dashboard(request):
    """Главная панель администратора - единая точка входа во все системы управления"""
    if not request.user.is_staff:
        return redirect('Visitor:user-login')
    
    from django.db.models import Sum, Count, Avg
    from django.utils import timezone
    from datetime import timedelta
    from donations.models import Donation, WeeklyReport, BonusPaymentRegistry
    from Asistent.models import ContentTask, TaskAssignment, AISchedule
    
    # Общая статистика сайта
    site_stats = {
        'total_posts': Post.objects.filter(status='published').count(),
        'total_authors': User.objects.filter(author_posts__isnull=False).distinct().count(),
        'total_users': User.objects.count(),
        'total_comments': Comment.objects.filter(active=True).count(),
    }
    
    # Статистика за последние 7 дней
    week_ago = timezone.now() - timedelta(days=7)
    recent_stats = {
        'posts_week': Post.objects.filter(created__gte=week_ago, status='published').count(),
        'comments_week': Comment.objects.filter(created__gte=week_ago, active=True).count(),
        'donations_week': Donation.objects.filter(
            completed_at__gte=week_ago,
            status='succeeded'
        ).aggregate(total=Sum('amount'))['total'] or 0,
    }
    
    # Статистика AI и заданий
    ai_stats = {
        'active_schedules': AISchedule.objects.filter(is_active=True).count(),
        'tasks_pending': ContentTask.objects.filter(status='available').count(),
        'tasks_in_progress': TaskAssignment.objects.filter(status='in_progress').count(),
        'tasks_for_review': TaskAssignment.objects.filter(status='completed').count(),
    }
    
    # Статистика социальных сетей
    try:
        from Sozseti.models import SocialChannel, PostPublication
        sozseti_stats = {
            'total_channels': SocialChannel.objects.filter(is_active=True).count(),
            'total_subscribers': sum(ch.subscribers_count for ch in SocialChannel.objects.filter(platform__name='telegram')),
            'publications_week': PostPublication.objects.filter(
                published_at__gte=week_ago,
                status='published'
            ).count(),
            'top_channel': SocialChannel.objects.filter(platform__name='telegram').order_by('-subscribers_count').first(),
        }
    except Exception:
        sozseti_stats = {
            'total_channels': 0,
            'total_subscribers': 0,
            'publications_week': 0,
            'top_channel': None,
        }
    
    # Статистика бонусов
    bonus_stats = {
        'pending_payments': BonusPaymentRegistry.objects.filter(
            status__in=['pending', 'partial']
        ).count(),
        'pending_amount': BonusPaymentRegistry.objects.filter(
            status__in=['pending', 'partial']
        ).aggregate(total=Sum('amount_to_pay'))['total'] or 0,
        'latest_report': WeeklyReport.objects.filter(is_finalized=True).order_by('-week_start').first(),
    }
    
    # Проверка Django-Q с актуальным сервисом
    from Asistent.services.djangoq_monitor import check_djangoq_status
    djangoq_status = check_djangoq_status()
    
    # Статистика по заданиям авторов
    from Asistent.models import ContentTask, TaskAssignment
    content_tasks_stats = {
        'available': ContentTask.objects.filter(status='available').count(),
        'active': TaskAssignment.objects.filter(status='in_progress').count(),
        'completed_week': TaskAssignment.objects.filter(
            status__in=['completed', 'approved'],
            completed_at__gte=week_ago
        ).count(),
        'total': ContentTask.objects.count(),
        'active_authors': TaskAssignment.objects.filter(
            status='in_progress'
        ).values('author').distinct().count(),
        'avg_reward': ContentTask.objects.filter(
            status='available'
        ).aggregate(avg=Sum('reward'))['avg'] or 0,
    }
    
    # Статистика по расписаниям AI
    from Asistent.models import AISchedule
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    ai_schedules_stats = {
        'active': AISchedule.objects.filter(is_active=True).count(),
        'inactive': AISchedule.objects.filter(is_active=False).count(),
        'total': AISchedule.objects.count(),
        'generated_today': Post.objects.filter(
            author__username='AI',
            created__gte=today_start
        ).count(),
        'total_articles': Post.objects.filter(author__username='AI').count(),
        'success_rate': 95,  # Можно вычислить из истории генераций
    }
    
    # Статистика рекламы
    try:
        from advertising.models import AdCampaign, Advertiser, AdClick
        from decimal import Decimal
        
        month_ago = timezone.now() - timedelta(days=30)
        
        # Доход за месяц
        revenue_month = Decimal('0.00')
        for click in AdClick.objects.filter(clicked_at__gte=month_ago):
            if click.ad_banner:
                revenue_month += click.ad_banner.campaign.cost_per_click
            elif click.context_ad:
                revenue_month += click.context_ad.cost_per_click
        
        ad_stats = {
            'active_campaigns': AdCampaign.objects.filter(is_active=True).count(),
            'total_advertisers': Advertiser.objects.filter(is_active=True).count(),
            'revenue_month': revenue_month,
        }
    except:
        ad_stats = {
            'active_campaigns': 0,
            'total_advertisers': 0,
            'revenue_month': 0,
        }
    
    # ============================================
    # Статистика доходов для виджета
    # ============================================
    period_days = 7
    period_start = timezone.now() - timedelta(days=period_days)
    
    # Все успешные платежи за период
    donations_period = Donation.objects.filter(
        status='succeeded',
        completed_at__gte=period_start
    )
    
    # Общая сумма
    total_revenue = donations_period.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    # Средний чек
    avg_check = donations_period.aggregate(
        avg=Avg('amount')
    )['avg'] or Decimal('0.00')
    
    # Количество транзакций
    transactions_count = donations_period.count()
    
    # Разбивка по источникам (payment_purpose)
    breakdown = {
        'donations': donations_period.filter(
            payment_purpose='donation'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        
        'premium': donations_period.filter(
            payment_purpose__startswith='premium_'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        
        'ai_coauthor': donations_period.filter(
            Q(payment_purpose__startswith='ai_')
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        
        'marathons': donations_period.filter(
            payment_purpose__startswith='marathon_'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
        
        'advertising': donations_period.filter(
            payment_purpose__startswith='ad_'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'),
    }
    
    # Топ-3 источника
    sources_list = [
        {'name': '💝 Донаты', 'key': 'donations', 'amount': breakdown['donations']},
        {'name': '💎 Premium', 'key': 'premium', 'amount': breakdown['premium']},
        {'name': '🤖 AI-Соавтор', 'key': 'ai_coauthor', 'amount': breakdown['ai_coauthor']},
        {'name': '📚 Марафоны', 'key': 'marathons', 'amount': breakdown['marathons']},
        {'name': '📢 Реклама', 'key': 'advertising', 'amount': breakdown['advertising']},
    ]
    top_sources = sorted(sources_list, key=lambda x: x['amount'], reverse=True)[:3]
    
    # Данные для графика (последние 7 дней)
    chart_labels = []
    chart_data = []
    
    for i in range(period_days - 1, -1, -1):
        day = timezone.now() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        day_total = Donation.objects.filter(
            status='succeeded',
            completed_at__gte=day_start,
            completed_at__lt=day_end
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        chart_labels.append(day.strftime('%d.%m'))
        chart_data.append(float(day_total))
    
    # Собираем всё в один dict
    revenue_stats = {
        'total_revenue': total_revenue,
        'avg_check': avg_check,
        'transactions_count': transactions_count,
        'breakdown': breakdown,
        'top_sources': top_sources,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'period_days': period_days,
    }
    
    # Категории для меню
    categorys = cache.get('categorys_list')
    if categorys is None:
        categorys = Category.objects.all()
        cache.set('categorys_list', categorys, 300)
    
    context = {
        'page_title': 'Панель администратора - IdealImage.ru',
        'page_description': 'Главная панель управления сайтом IdealImage.ru',
        'site_stats': site_stats,
        'recent_stats': recent_stats,
        'ai_stats': ai_stats,
        'bonus_stats': bonus_stats,
        'ad_stats': ad_stats,
        'djangoq_status': djangoq_status,
        'content_tasks_stats': content_tasks_stats,
        'ai_schedules_stats': ai_schedules_stats,
        'revenue_stats': revenue_stats,
        'sozseti_stats': sozseti_stats,
        'categorys': categorys,
    }
    
    return render(request, 'admin/master_dashboard.html', context)
