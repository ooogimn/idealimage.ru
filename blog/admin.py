from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin
from django.utils.safestring import mark_safe
from django.db.models import Count
from .models import *
from .models_likes import Like, PostRating, Bookmark
from mptt.admin import DraggableMPTTAdmin
from taggit.forms import TagField
from taggit.models import Tag
from taggit.admin import TagAdmin as TaggitTagAdmin
from .forms import PostAdminForm

# Unregister the default TagAdmin
admin.site.unregister(Tag)


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    """    Админ-панель модели категорий    """
    list_display = ('id','tree_actions', 'title', 'posts_count', 'post_photo_cat')
    list_display_links = ( 'id','title','post_photo_cat')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ['post_photo_cat']
    
    fieldsets = (
        ('ЗАГОЛОВКИ', {'fields': ('title', 'slug', 'parent')}),
        ('ОСНОВНОЙ КОНТЕНТ', {'fields': ('post_photo_cat', 'kartinka',  'description')}),
        ('Дополнения', {'fields': ('chat_id', 'chat_url', )})
    )
    
    def get_queryset(self, request):
        """Переопределяем queryset для добавления подсчета статей"""
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            _posts_count=Count('posts', distinct=True)
        )
        return queryset
    
    @admin.display(description="Количество статей", ordering='_posts_count')
    def posts_count(self, obj):
        """Отображение количества статей в категории"""
        count = getattr(obj, '_posts_count', 0)
        if count > 0:
            return mark_safe(f'<strong style="color: green;">{count}</strong>')
        return mark_safe(f'<span style="color: gray;">{count}</span>')
    
    @admin.display(description="Изображение", ordering='content')
    def post_photo_cat(self, Blog: Category):
        if Blog.kartinka:
            return mark_safe(f"<img src='{Blog.kartinka.url}' width=70>")
        return "Без фото"


#def telega_change(modeladmin, request, queryset):
#    for post_obj in queryset:
#        if post_obj.fixed == False and post_obj.status == 'draft' :
#            send_telegram_message(
#                chat_id=post_obj.category.chat_id,
#                post=post_obj
#            )
#            post_obj.fixed = True
#            post_obj.status = 'published'
#            post_obj.save()    
#telega_change.short_description = "ОПУБЛИКОВАТЬ"

# ============================================================================
# ДЕЙСТВИЯ (ACTIONS) ДЛЯ МАССОВОГО УПРАВЛЕНИЯ СТАТЬЯМИ
# ============================================================================

@admin.action(description="📝 Перевести в черновик")
def ststus_change(modeladmin, request, queryset):
    """Перевести статус в черновик"""
    count = queryset.update(status='draft')
    modeladmin.message_user(request, f'Статус изменен на "Черновик" для {count} статей')


@admin.action(description="📌 Добавить ФИКСАЦИЮ")
def fixed_add(modeladmin, request, queryset):
    """Добавить фиксацию"""
    count = queryset.update(fixed=True)
    modeladmin.message_user(request, f'Фиксация добавлена для {count} статей')


@admin.action(description="📌 Снять фиксацию")
def fixed_remove(modeladmin, request, queryset):
    """Снять фиксацию"""
    count = queryset.update(fixed=False)
    modeladmin.message_user(request, f'Фиксация снята для {count} статей')


@admin.action(description="✅ Пометить как опубликованные в Telegram")
def telegram_mark_as_posted(modeladmin, request, queryset):
    """Пометить как опубликованные в Telegram"""
    from django.utils import timezone
    count = 0
    for post in queryset:
        if not post.telegram_posted_at:
            post.telegram_posted_at = timezone.now()
            post.save(update_fields=['telegram_posted_at'])
            count += 1
    modeladmin.message_user(request, f'Помечено как опубликованные в Telegram: {count} статей')


@admin.action(description="❌ Снять метку публикации в Telegram")
def telegram_mark_as_not_posted(modeladmin, request, queryset):
    """Снять метку публикации в Telegram"""
    count = 0
    for post in queryset:
        if post.telegram_posted_at:
            post.telegram_posted_at = None
            post.save(update_fields=['telegram_posted_at'])
            count += 1
    modeladmin.message_user(request, f'Метка публикации снята для {count} статей')


@admin.action(description="🔄 Перезапустить обработку видео/фото")
def restart_video_processing_action(modeladmin, request, queryset):
    """Принудительно перезапустить обработку медиа/видео"""
    from .tasks import process_media_task
    count = 0
    for post in queryset:
        if post.kartinka:
            # Сбрасываем статус, чтобы сигнал или задача не считали её готовой
            post.video_processing_status = 'pending'
            post.video_optimized = False
            post.save(update_fields=['video_processing_status', 'video_optimized'])
            process_media_task.delay(post.id)
            count += 1
    modeladmin.message_user(request, f'Запущена фоновая обработка для {count} медиа-файлов')

# ============================================================================
# КАСТОМНЫЕ ФИЛЬТРЫ ДЛЯ АДМИНКИ
# ============================================================================

class TelegramPostedFilter(admin.SimpleListFilter):
    """Фильтр по статусу публикации в Telegram"""
    title = 'Публикация в Telegram'
    parameter_name = 'telegram_posted'

    def lookups(self, request, model_admin):
        return (
            ('posted', '✅ Опубликовано в Telegram'),
            ('not_posted', '❌ НЕ опубликовано в Telegram'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'posted':
            return queryset.filter(telegram_posted_at__isnull=False)
        if self.value() == 'not_posted':
            return queryset.filter(telegram_posted_at__isnull=True)
        return queryset


class FixedFilter(admin.SimpleListFilter):
    """Фильтр по фиксации статей"""
    title = 'Фиксация'
    parameter_name = 'is_fixed'

    def lookups(self, request, model_admin):
        return (
            ('fixed', '📌 С фиксацией'),
            ('not_fixed', '📄 Без фиксации'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'fixed':
            return queryset.filter(fixed=True)
        if self.value() == 'not_fixed':
            return queryset.filter(fixed=False)
        return queryset


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    """    Админ-панель модели Post    """
    form = PostAdminForm
    
    list_display = ['title', 'post_photo', 'category', 'fixed_icon', 'video_status_icon', 'telegram_icon', 'moderation_icon', 'status', 'author', 'created']
    list_display_links = ['title', 'post_photo', 'category']
    list_filter = ['status', 'moderation_status', TelegramPostedFilter, FixedFilter, 'category', 'author', 'created']
    search_fields = ['title', 'content', 'author__username']
    prepopulated_fields = {'slug': ('title',)}
    raw_id_fields = ['category']
    # date_hierarchy = 'created'  # Временно отключено из-за MySQL timezone tables
    ordering = ['-created']  # Новые статьи сверху
    save_on_top = True
    readonly_fields = ['post_photo', 'video_optimized', 'video_processing_status', 'video_duration', 'video_preview_preview']
    actions = [
        ststus_change, 
        fixed_add, 
        fixed_remove, 
        telegram_mark_as_posted, 
        telegram_mark_as_not_posted,
        restart_video_processing_action
    ]
    
    # Настройка пагинации
    list_per_page = 20  # По умолчанию показывать 20 статей
    list_max_show_all = 100  # Максимум для "Показать все"
    
    class Media:
        js = ('admin/js/per_page_selector.js',)
    
    def changelist_view(self, request, extra_context=None):
        """Переопределяем для добавления выбора количества элементов на странице"""
        # Получаем количество элементов из параметров
        per_page_param = request.GET.get('per_page')
        if per_page_param:
            try:
                custom_per_page = int(per_page_param)
                if custom_per_page in [20, 50, 75, 100]:
                    self.list_per_page = custom_per_page
            except (ValueError, TypeError):
                pass
        
        return super().changelist_view(request, extra_context)
    
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('title', 'slug', 'category', 'author', 'status', 'fixed')
        }),
        ('Содержание', {
            'fields': ('description', 'content'),
            'classes': ('wide',)
        }),
        ('Медиа', {
            'fields': (
                'kartinka', 'video_url', 'post_photo', 
                'video_poster', 'video_preview', 'video_preview_preview',
                'thumbnail', 'video_optimized', 'video_processing_status', 'video_duration'
            ),
            'classes': ('wide',),
            'description': 'Загрузите изображение/видео или укажите ссылку на видео. Видео/фото автоматически оптимизируются при загрузке.'
        }),
        ('AI Модерация', {
            'fields': ('moderation_status', 'ai_moderation_notes'),
            'classes': ('collapse',),
            'description': '🤖 Результаты проверки AI Agent'
        }),
        ('ТЕГГИ', {
            'fields': ('tags',),
            'classes': ('collapse',)
        }),
        ('Социальные сети', {
            'fields': ('telegram_posted_at',),
            'classes': ('collapse',)
        }),
    )

    
    
    

    @admin.display(description="Превью", ordering='content')
    def post_photo(self, blog: Post):
        if blog.video_url:
            return mark_safe(f'<div><strong>🎥 Видео:</strong><br><a href="{blog.video_url}" target="_blank">{blog.video_url[:50]}...</a></div>')
        elif blog.kartinka:
            # Проверяем, это видео или изображение
            if blog.kartinka.name and any(blog.kartinka.name.endswith(ext) for ext in ['.mp4', '.webm', '.mov']):
                return mark_safe(f'<div><strong>🎥 Видео:</strong><br><video src="{blog.kartinka.url}" width="80" controls></video></div>')
            else:
                return mark_safe(f"<img src='{blog.kartinka.url}' width=80>")
        return "Без медиа"
    
    @admin.display(description="📌", ordering='fixed', boolean=False)
    def fixed_icon(self, obj):
        """Иконка фиксации статьи"""
        if obj.fixed:
            return mark_safe('<span style="font-size: 20px; color: #28a745;" title="Зафиксирована">📌</span>')
        return mark_safe('<span style="font-size: 16px; color: #ccc;" title="Не зафиксирована">📄</span>')
    
    @admin.display(description="📱", ordering='telegram_posted_at', boolean=False)
    def telegram_icon(self, obj):
        """Иконка публикации в Telegram"""
        if obj.telegram_posted_at:
            date_str = obj.telegram_posted_at.strftime('%d.%m.%Y %H:%M')
            return mark_safe(
                f'<span style="font-size: 20px; color: #0088cc;" title="Опубликовано в Telegram: {date_str}">✅</span>'
            )
        return mark_safe('<span style="font-size: 18px; color: #dc3545;" title="НЕ опубликовано в Telegram">❌</span>')
    
    @admin.display(description="🤖", ordering='moderation_status', boolean=False)
    def moderation_icon(self, obj):
        """Иконка модерации AI Agent"""
        if obj.moderation_status == 'approved':
            return mark_safe(
                f'<span style="font-size: 20px; color: #28a745;" title="✅ Одобрено AI Agent">✅</span>'
            )
        elif obj.moderation_status == 'rejected':
            notes = obj.ai_moderation_notes[:200] if obj.ai_moderation_notes else 'Не указаны'
            return mark_safe(
                f'<span style="font-size: 20px; color: #dc3545;" title="❌ Отклонено AI Agent\n\nПРИЧИНЫ:\n{notes}">❌</span>'
            )
        elif obj.moderation_status == 'pending':
            return mark_safe(
                f'<span style="font-size: 18px; color: #ffc107;" title="⏳ На модерации AI">⏳</span>'
            )
        return mark_safe(
            f'<span style="font-size: 16px; color: #6c757d;" title="Модерация пропущена">⊘</span>'
        )

    @admin.display(description="🎬", ordering='video_processing_status')
    def video_status_icon(self, obj):
        """Иконка статуса обработки видео"""
        if not obj.kartinka:
            return "—"
            
        name = obj.kartinka.name.lower()
        is_video = any(name.endswith(ext) for ext in ['.mp4', '.webm', '.mov', '.avi', '.mkv'])
        
        if not is_video:
            # Для фото показываем статус на основе наличия thumbnail
            if obj.thumbnail:
                return mark_safe('<span style="color: #28a745;" title="Фото оптимизировано (WebP + Thumb)">🖼️✅</span>')
            return mark_safe('<span style="color: #ffc107;" title="Фото в очереди на оптимизацию">🖼️⏳</span>')

        # Статусы для видео
        if obj.video_processing_status == 'completed':
            return mark_safe('<span style="font-size: 18px; color: #28a745;" title="✅ Видео полностью обработано (Оптимизировано + Превью + Poster)">🎬✅</span>')
        elif obj.video_processing_status == 'processing':
            return mark_safe('<span style="font-size: 18px; color: #ffc107;" title="⏳ Видео в процессе обработки...">🎬⏳</span>')
        elif obj.video_processing_status == 'failed':
            return mark_safe('<span style="font-size: 18px; color: #dc3545;" title="❌ Ошибка при обработке видео">🎬❌</span>')
        elif obj.video_processing_status == 'pending':
            return mark_safe('<span style="font-size: 18px; color: #6c757d;" title="📽️ Видео ожидает обработки">🎬📽️</span>')
        return "—"

    @admin.display(description="Просмотр превью")
    def video_preview_preview(self, obj):
        """Отображение 5-секундного превью в админке"""
        if obj.video_preview:
            return mark_safe(f'<video src="{obj.video_preview.url}" width="200" autoplay loop muted playsinline></video>')
        return "Превью не создано"
        
    #def response_change(self, request, post_obj):
    #    if post_obj.fixed == True and post_obj.status == 'draft' :
    #        send_telegram_message(
    #            chat_id=post_obj.category.chat_id,
    #            post=post_obj
    #        )
    #        post_obj.fixed = True
    #        post_obj.status = 'published'
    #        post_obj.save()
    #        self.message_user(request, "Опубликовано сообщение об этом посте в телеграм канале")
        
    #    return super().response_change(request, post_obj)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """
    Админ-панель модели комментариев
    """
    list_display = ('author_comment', 'content', 'active', 'email', 'post', 'created')
    list_filter = ('active', 'created', 'updated', 'post')
    search_fields = ('author_comment', 'email', 'content', 'post')
    
    # Настройка пагинации
    list_per_page = 20
    list_max_show_all = 100
    
    class Media:
        js = ('admin/js/per_page_selector.js',)
    
    def changelist_view(self, request, extra_context=None):
        """Переопределяем для добавления выбора количества элементов на странице"""
        # Получаем количество элементов из параметров
        per_page_param = request.GET.get('per_page')
        if per_page_param:
            try:
                custom_per_page = int(per_page_param)
                if custom_per_page in [20, 50, 75, 100]:
                    self.list_per_page = custom_per_page
            except (ValueError, TypeError):
                pass
        
        return super().changelist_view(request, extra_context)
    

@admin.register(Tag)
class TagAdmin(TaggitTagAdmin):
    list_display = ['name', 'slug', 'post_count']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            post_count=Count('taggit_taggeditem_items')
        ).order_by('-post_count', 'name')

    @admin.display(description='Количество статей')
    def post_count(self, obj):
        return obj.post_count


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    """Админ-панель для лайков"""
    list_display = ('user_display', 'post', 'reaction_type', 'created')
    list_filter = ('reaction_type', 'created')
    search_fields = ('user__username', 'post__title', 'session_key')
    readonly_fields = ('created',)
    # date_hierarchy = 'created'  # Временно отключено из-за MySQL timezone tables
    
    # Настройка пагинации
    list_per_page = 20
    list_max_show_all = 100
    
    @admin.display(description='Пользователь')
    def user_display(self, obj):
        if obj.user:
            return obj.user.username
        elif obj.session_key:
            return f'Анонимный ({obj.session_key[:8]}...)'
        return 'Неизвестно'


@admin.register(PostRating)
class PostRatingAdmin(admin.ModelAdmin):
    """Админ-панель для рейтингов"""
    list_display = ('user', 'post', 'rating', 'created', 'updated')
    list_filter = ('rating', 'created')
    search_fields = ('user__username', 'post__title')
    readonly_fields = ('created', 'updated')
    # date_hierarchy = 'created'  # Временно отключено из-за MySQL timezone tables
    
    # Настройка пагинации
    list_per_page = 20
    list_max_show_all = 100


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    """Админ-панель для закладок"""
    list_display = ('user', 'post', 'created')
    list_filter = ('created',)
    search_fields = ('user__username', 'post__title')
    readonly_fields = ('created',)
    # date_hierarchy = 'created'  # Временно отключено из-за MySQL timezone tables
    
    # Настройка пагинации
    list_per_page = 20
    list_max_show_all = 100


@admin.register(URLRedirect)
class URLRedirectAdmin(admin.ModelAdmin):
    """Админ-панель для редиректов URL"""
    list_display = ('old_url', 'new_url', 'redirect_type', 'hits_count', 'last_seen', 'is_active')
    list_filter = ('redirect_type', 'is_active', 'first_seen')
    search_fields = ('old_url', 'new_url')
    readonly_fields = ('hits_count', 'first_seen', 'last_seen')
    list_editable = ('is_active',)
    ordering = ('-hits_count', '-last_seen')
    # date_hierarchy = 'first_seen'  # Временно отключено из-за MySQL timezone tables
    
    # Настройка пагинации
    list_per_page = 20
    list_max_show_all = 100
    
    fieldsets = (
        ('URL', {
            'fields': ('old_url', 'new_url', 'redirect_type')
        }),
        ('Статистика', {
            'fields': ('hits_count', 'first_seen', 'last_seen'),
            'classes': ('collapse',)
        }),
        ('Настройки', {
            'fields': ('is_active', 'notes')
        }),
    )


