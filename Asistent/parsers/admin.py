"""
Админка для системы парсинга статей.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.utils import timezone
from .models import ParsingCategory, ParsedArticle


@admin.register(ParsingCategory)
class ParsingCategoryAdmin(admin.ModelAdmin):
    """Админка категорий парсинга."""
    
    list_display = [
        'name_with_status',
        'site_category',
        'articles_per_day',
        'sources_display',
        'updated_at'
    ]
    list_filter = ['is_active', 'site_category']
    search_fields = ['name']
    change_list_template = 'admin/parsers/parsingcategory/change_list.html'
    
    def get_urls(self):
        """Добавляем кастомный URL для ручного запуска парсинга."""
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                'run-parsing/',
                self.admin_site.admin_view(self.run_parsing),
                name='Parsers_parsingcategory_run_parsing',
            ),
        ]
        return custom_urls + urls
    
    def run_parsing(self, request):
        """Ручной запуск парсинга статей."""
        from .tasks import daily_article_parsing
        
        try:
            # Запускаем задачу асинхронно через Celery
            daily_article_parsing.delay()
            messages.success(
                request,
                "✅ Задача парсинга статей запущена! Результаты будут доступны в логах Celery и в списке спаршенных статей."
            )
        except Exception as e:
            messages.error(
                request,
                f"❌ Ошибка запуска парсинга: {str(e)}"
            )
        
        return HttpResponseRedirect(reverse('admin:Parsers_parsingcategory_changelist'))
    
    fieldsets = (
        ('🔧 Основное', {
            'fields': ('name', 'is_active', 'site_category'),
        }),
        ('🔍 Поиск', {
            'fields': ('search_queries', 'sources'),
            'description': 'Поисковые запросы (JSON массив) и источники (JSON массив: ["google", "yandex", "rss", "social"])'
        }),
        ('⚙️ Настройки', {
            'fields': ('articles_per_day',),
        }),
        ('📅 Информация', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def name_with_status(self, obj):
        """Название со статусом."""
        icon = "✅" if obj.is_active else "⏸️"
        return f"{icon} {obj.name}"
    name_with_status.short_description = "Категория"
    
    def sources_display(self, obj):
        """Отображение источников."""
        sources = obj.sources or []
        if not sources:
            return "—"
        return ", ".join(sources)
    sources_display.short_description = "Источники"


@admin.register(ParsedArticle)
class ParsedArticleAdmin(admin.ModelAdmin):
    """Админка спаршенных статей."""
    
    list_display = [
        'status_icon',
        'title_short',
        'category',
        'source_name',
        'popularity_score',
        'selected_for_posting',
        'published_article_link',
        'parsed_at'
    ]
    list_filter = ['status', 'selected_for_posting', 'category', 'parsing_category', 'parsed_at']
    search_fields = ['title', 'source_name', 'source_url']
    date_hierarchy = 'parsed_at'
    readonly_fields = ['parsed_at', 'notes']
    
    fieldsets = (
        ('📄 Статья', {
            'fields': ('title', 'content', 'source_url', 'source_name'),
        }),
        ('📂 Категории', {
            'fields': ('category', 'parsing_category'),
        }),
        ('📊 Статус', {
            'fields': ('status', 'selected_for_posting', 'popularity_score'),
        }),
        ('🔗 Связи', {
            'fields': ('published_article',),
        }),
        ('📝 Заметки', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
        ('📅 Информация', {
            'fields': ('parsed_at',),
            'classes': ('collapse',),
        }),
    )
    
    actions = ['mark_for_posting', 'mark_as_approved', 'mark_as_rejected', 'delete_selected']
    
    def status_icon(self, obj):
        """Иконка статуса."""
        icons = {
            'pending': '⏳',
            'approved': '✅',
            'rejected': '❌',
            'published': '📤'
        }
        return format_html('<span style="font-size: 20px;">{}</span>', icons.get(obj.status, '❓'))
    status_icon.short_description = ""
    
    def title_short(self, obj):
        """Короткий заголовок."""
        return obj.title[:60] + "..." if len(obj.title) > 60 else obj.title
    title_short.short_description = "Заголовок"
    
    def published_article_link(self, obj):
        """Ссылка на опубликованную статью."""
        if obj.published_article:
            url = reverse('admin:blog_post_change', args=[obj.published_article.id])
            return format_html('<a href="{}">{}</a>', url, obj.published_article.title[:50])
        return "—"
    published_article_link.short_description = "Опубликованная статья"
    
    def mark_for_posting(self, request, queryset):
        """Пометить для публикации."""
        count = queryset.update(selected_for_posting=True, status='approved')
        self.message_user(request, f"{count} статей помечено для публикации.")
    mark_for_posting.short_description = "✅ Пометить для публикации"
    
    def mark_as_approved(self, request, queryset):
        """Одобрить статьи."""
        count = queryset.update(status='approved')
        self.message_user(request, f"{count} статей одобрено.")
    mark_as_approved.short_description = "✅ Одобрить"
    
    def mark_as_rejected(self, request, queryset):
        """Отклонить статьи."""
        count = queryset.update(status='rejected', selected_for_posting=False)
        self.message_user(request, f"{count} статей отклонено.")
    mark_as_rejected.short_description = "❌ Отклонить"
    
    def delete_selected(self, request, queryset):
        """Удалить выбранные статьи."""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} статей удалено.")
    delete_selected.short_description = "🗑️ Удалить выбранные"

