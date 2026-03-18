from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.html import strip_tags

# Импорты для обратной совместимости и fallback
from Asistent.gigachat_api import get_gigachat_client, RateLimitCooldown
from Asistent.models import AIGeneratedArticle
from Asistent.parsers.universal_parser import UniversalParser
from Asistent.seo_advanced import AdvancedSEOOptimizer
from Asistent.constants import ZODIAC_SIGNS
from Asistent.utils import resolve_dynamic_params
from Asistent.formatting import render_markdown, MarkdownPreset
from Asistent.services.telegram_client import get_telegram_client
from Asistent.services.yandex_webmaster import get_yandex_webmaster_client
from blog.models import Category, Post

from .context import ScheduleContext
from .models import AISchedule
from .interfaces import (
    get_content_generator,
    get_seo_optimizer,
    get_content_parser,
    get_formatter,
    get_utils,
)


logger = logging.getLogger(__name__)

MONTH_NAMES = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
]
WEEKDAY_NAMES = [
    'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'
]

"""Генерация статей через промпт-шаблон"""
class PromptGenerationWorkflow:
    """
    Полный цикл генерации статей через промпт-шаблон.
    Переносит прежнюю реализацию run_prompt_schedule в объектную форму.
    """

    def __init__(self, schedule: AISchedule, context: ScheduleContext):
        self.schedule = schedule
        self.context = context
        self.template = schedule.prompt_template
        self.parser = UniversalParser()
        self.optimizer = AdvancedSEOOptimizer()
        self.client = get_gigachat_client()
        self.ai_user = self._get_or_create_ai_user()

    class RateLimitExceeded(Exception):
        def __init__(self, message: str, retry_after: int = 300):
            super().__init__(message)
            self.retry_after = retry_after

    def run(self, current_time: datetime) -> Dict:
        """
        РЕФАКТОРИНГ: используются сервисы из Test_Promot для генерации.
        Уникальная логика расписания сохранена.
        """
        if not self.template:
            raise ValueError("У расписания отсутствует промпт-шаблон")

        static_params = dict(self.schedule.static_params or {})
        dynamic_config = dict(self.schedule.dynamic_params or {})
        articles_per_run = max(self.schedule.articles_per_run or 1, 1)
        payload = self._get_schedule_payload()

        daily_limit = payload.get('daily_limit')
        if daily_limit is not None:
            try:
                daily_limit = max(int(daily_limit), 1)
                ai_user = self.ai_user
                today_count_qs = Post.objects.filter(
                    author=ai_user,
                    created__date=current_time.date(),
                    status='published',
                )
                if self.schedule.category_id:
                    today_count_qs = today_count_qs.filter(category_id=self.schedule.category_id)
                today_count = today_count_qs.count()
                if today_count >= daily_limit:
                    result = {
                        'success': True,
                        'status': 'skipped',
                        'schedule_id': self.schedule.id,
                        'schedule_name': self.schedule.name,
                        'created_posts': 0,
                        'created_count': 0,
                        'errors': [],
                        'reason': 'daily_limit_reached',
                        'daily_limit': daily_limit,
                        'created_today': today_count,
                    }
                    self.context.add_log('info', 'Daily limit reached', {
                        'daily_limit': daily_limit,
                        'created_today': today_count,
                    })
                    self.context.set_result(**result)
                    return result
            except Exception:
                logger.exception("Не удалось применить daily_limit для расписания %s", self.schedule.id)

        created_posts: List[Post] = []
        errors: List[str] = []

        for article_index in range(articles_per_run):
            try:
                generation_start = time.time()
                resolved_dynamic = resolve_dynamic_params(dynamic_config, self.schedule.id) if dynamic_config else {}
                target_category = self._select_target_category()

                # РЕФАКТОРИНГ: подготовка параметров
                params = self._prepare_parameters_via_service(
                    static_params=static_params,
                    resolved_dynamic=resolved_dynamic,
                    current_time=current_time,
                    article_index=article_index,
                    total=articles_per_run,
                    target_category=target_category,
                )

                # РЕФАКТОРИНГ: генерация контента через Test_Promot
                article_text, source_urls_used, api_calls = self._generate_content_via_service(params)
                if not article_text:
                    raise ValueError("AI вернул пустой ответ")

                # РЕФАКТОРИНГ: обработка заголовка и контента
                title, content_html = self._postprocess_article_via_service(article_text, params)

                # Создание поста (уникальная логика расписания)
                post = self._create_post(title, content_html, params, target_category=target_category)

                # РЕФАКТОРИНГ: генерация изображения через Test_Promot
                image_path, image_info = self._generate_image_via_service(params, title)
                if image_path:
                    post.kartinka = image_path
                    post.save(update_fields=['kartinka'])

                # РЕФАКТОРИНГ: применение тегов через Test_Promot
                self._apply_tags_via_service(post, params)
                created_posts.append(post)

                generation_time = int(time.time() - generation_start)
                prompt_text = self._build_prompt(params, params.get('weather_forecast'))

                # РЕФАКТОРИНГ: сохранение метаданных через сервис
                from Asistent.Test_Promot.services import ScheduleMetadataService
                ScheduleMetadataService.save_metadata(
                    schedule=self.schedule,
                    post=post,
                    prompt_text=prompt_text,
                    ai_response=article_text,
                    source_urls=source_urls_used,
                    generation_time_seconds=generation_time,
                    api_calls_count=api_calls,
                )

                self.context.add_log('info', 'Article generated', {
                    'post_id': post.id,
                    'title': title,
                    'image_info': image_info,
                })

            except self.RateLimitExceeded as rate_error:
                logger.warning(
                    "   ⚠️ Превышен лимит GigaChat при генерации статьи #%s: %s",
                    article_index + 1,
                    rate_error,
                )
                errors.append(str(rate_error))
                return self._handle_rate_limit(
                    errors,
                    created_posts,
                    current_time,
                    retry_after=getattr(rate_error, 'retry_after', 300),
                )
            except Exception as article_error:
                logger.exception("   ❌ Ошибка генерации статьи #%s: %s", article_index + 1, article_error)
                errors.append(str(article_error))
                self.context.add_log('error', 'Article generation failed', {
                    'index': article_index + 1,
                    'error': str(article_error),
                })
                continue

        # РЕФАКТОРИНГ: обновление расписания через сервис
        self._update_schedule_timestamps_via_service(current_time)

        if created_posts:
            # РЕФАКТОРИНГ: уведомления через сервис
            from Asistent.Test_Promot.services import ScheduleNotificationService
            ScheduleNotificationService.send_notification(
                schedule=self.schedule,
                created_posts=created_posts,
                success=True
            )
            
            result = {
                'success': True,
                'status': 'success',
                'schedule_id': self.schedule.id,
                'schedule_name': self.schedule.name,
                'created_posts': len(created_posts),
                'created_count': len(created_posts),
                'errors': errors,
                'mode': 'prompt',
                'run_count': self.schedule.current_run_count,
                'max_runs': self.schedule.max_runs,
                'next_run': self.schedule.next_run.isoformat() if self.schedule.is_active else None,
            }
            self.context.set_result(**result)
            return result

        # Формируем детальное сообщение об ошибке
        error_message = "Не удалось создать статьи"
        if errors:
            error_details = "; ".join(errors[:3])  # Первые 3 ошибки
            if len(errors) > 3:
                error_details += f" (и ещё {len(errors) - 3} ошибок)"
            error_message = f"Не удалось создать статьи. Ошибки: {error_details}"
        
        # РЕФАКТОРИНГ: уведомления через сервис
        from Asistent.Test_Promot.services import ScheduleNotificationService
        ScheduleNotificationService.send_notification(
            schedule=self.schedule,
            created_posts=None,
            success=False,
            error=error_message
        )
        
        result = {
            'success': False,
            'status': 'failed',
            'schedule_id': self.schedule.id,
            'error': 'no_articles_created',
            'errors': errors,
            'created_count': 0,
        }
        self.context.set_result(**result)
        return result

    # -- helpers -----------------------------------------------------------------
    # РЕФАКТОРИНГ: новые методы, использующие сервисы из Test_Promot

    def _prepare_parameters_via_service(
        self,
        static_params: Dict,
        resolved_dynamic: Dict,
        current_time: datetime,
        article_index: int,
        total: int,
        target_category: Optional[Category] = None,
    ) -> Dict:
        """
        РЕФАКТОРИНГ: подготовка параметров через ContextBuilder из Test_Promot.
        Добавляет специфичные для расписания параметры.
        """
        from Asistent.Test_Promot.services import ContextBuilder
        
        # Объединяем параметры
        user_variables = {
            **static_params,
            **resolved_dynamic,
        }
        
        # Добавляем параметры расписания
        user_variables.update({
            'article_index': article_index + 1,
            'articles_per_run': total,
            'run_datetime': current_time.strftime('%d.%m.%Y %H:%M'),
            'run_date': current_time.strftime('%d.%m.%Y'),
        })
        if target_category:
            user_variables.setdefault('category', target_category.title)
            user_variables.setdefault('category_id', target_category.id)
        
        # Строим контекст через ContextBuilder
        builder = ContextBuilder(self.template, user_variables)
        params = builder.build()
        
        # Добавляем погоду (специфично для расписания)
        params.update(self._enrich_weather_context(params, current_time))
        
        return params
    
    def _generate_content_via_service(self, params: Dict) -> Tuple[str, List[str], int]:
        """
        РЕФАКТОРИНГ: генерация контента через ContentGenerationFactory из Test_Promot.
        
        Returns:
            (article_text, source_urls_used, api_calls_count)
        """
        from Asistent.Test_Promot.services import ContentGenerationFactory
        from Asistent.Test_Promot.test_prompt import (
            render_template_text,
            GIGACHAT_TIMEOUT_ARTICLE
        )
        
        # Строим промпт
        prompt = render_template_text(self.template.template or '', params)
        if not prompt.strip():
            raise ValueError("Промпт пустой после рендеринга")
        
        # Создаём стратегию генерации
        strategy = ContentGenerationFactory.create_strategy(
            self.template,
            self.client,
            GIGACHAT_TIMEOUT_ARTICLE,
            context=params  # Передаем контекст для автоматического формирования URL гороскопов
        )
        
        # Генерируем контент
        try:
            article_text, source_info = strategy.generate(prompt, params)
            
            # Извлекаем source_urls если есть
            source_urls_used = []
            if source_info:
                # Для ParseAndRewriteStrategy source_info содержит URL
                source_urls_used = [source_info]
            
            api_calls = 1  # Базовый вызов
            
            return article_text, source_urls_used, api_calls
        
        except RateLimitCooldown as e:
            raise self.RateLimitExceeded(str(e), retry_after=getattr(e, 'retry_after', 300))
        except Exception as e:
            # Проверяем на Rate Limit в тексте ошибки
            error_text = str(e)
            if '429' in error_text or 'Too Many Requests' in error_text:
                raise self.RateLimitExceeded('GigaChat вернул 429 Too Many Requests')
            raise
    
    def _postprocess_article_via_service(self, article_text: str, params: Dict) -> Tuple[str, str]:
        """
        РЕФАКТОРИНГ: обработка заголовка через TitleGenerator из Test_Promot.
        Добавляет FAQ и специфичную для расписания обработку.
        
        Returns:
            (title, content_html)
        """
        from Asistent.Test_Promot.services import TitleGenerator
        from Asistent.Test_Promot.test_prompt import GIGACHAT_TIMEOUT_TITLE
        
        # Генерируем заголовок через TitleGenerator
        title_generator = TitleGenerator(self.template, self.client, GIGACHAT_TIMEOUT_TITLE)
        title = title_generator.generate(params, article_text, provided_title=None)
        
        # Конвертируем markdown в HTML
        content_html = render_markdown(article_text, preset=MarkdownPreset.CKEDITOR)
        
        # Добавляем FAQ (из старой логики)
        sign = params.get('zodiac_sign')
        temp_post = Post(
            title=title,
            content=content_html,
            category=self.template.blog_category or self.schedule.category,
            author=self.ai_user
        )
        
        if 'faq-section' not in content_html.lower():
            faq_context = {'zodiac_sign': sign} if sign else None
            faq_result = self.optimizer.generate_faq_block(temp_post, context=faq_context)
            if faq_result.get('success') and faq_result.get('html'):
                content_html += '\n\n' + faq_result['html']
        
        # Добавляем прогноз погоды
        if params.get('weather_forecast'):
            content_html += (
                "\n\n<p style=\"margin-top:1.5em; font-weight:500;\">"
                f"🌦️ Прогноз погоды: {params['weather_forecast']}"
                "</p>"
            )
        
        # Нормализация для гороскопов
        if sign:
            content_html = self._normalize_zodiac_content(content_html, sign)
            if sign.lower() not in title.lower():
                title = f"{sign}: {title}"
        
        return title, content_html
    
    def _generate_image_via_service(self, params: Dict, title: str) -> Tuple[Optional[str], str]:
        """
        РЕФАКТОРИНГ: генерация изображения через ImageProcessor из Test_Promot.
        
        Returns:
            (image_path, image_info)
        """
        from Asistent.Test_Promot.services import ImageProcessor
        
        # Обновляем контекст для генерации изображения
        context = dict(params)
        context['title'] = title
        
        # Обрабатываем изображение через ImageProcessor
        processor = ImageProcessor(self.template, self.client)
        
        try:
            result = processor.process(context)
            return result.path, result.info
        
        except RateLimitCooldown as e:
            logger.warning("   ⏸️ GigaChat в cooldown при генерации изображения: %s", e)
            raise self.RateLimitExceeded(str(e), retry_after=getattr(e, 'retry_after', 300))
        except Exception as e:
            logger.error("   ❌ Ошибка генерации изображения: %s", e, exc_info=True)
            return None, f"Ошибка генерации: {e}"
    
    def _apply_tags_via_service(self, post: Post, params: Dict) -> None:
        """
        РЕФАКТОРИНГ: применение тегов через TagProcessor из Test_Promot.
        """
        from Asistent.Test_Promot.services import TagProcessor
        
        tag_processor = TagProcessor(self.template)
        valid_tags = tag_processor.generate(params)
        
        for tag in valid_tags:
            post.tags.add(tag)
        
        if valid_tags:
            logger.info(f"   🏷️ Добавлено тегов: {len(valid_tags)}")
    
    def _update_schedule_timestamps_via_service(self, current_time: datetime) -> None:
        """
        РЕФАКТОРИНГ: обновление расписания через ScheduleTimestampService из Test_Promot.
        """
        from Asistent.Test_Promot.services import ScheduleTimestampService
        
        interval_minutes = self.schedule.interval_minutes if self.schedule.schedule_kind == 'interval' else None
        
        ScheduleTimestampService.update_schedule_after_run(
            schedule=self.schedule,
            current_time=current_time,
            interval_minutes=interval_minutes
        )

    # -- старые методы (сохранены для совместимости) -----------------------------

    def _prepare_parameters(
        self,
        static_params: Dict,
        resolved_dynamic: Dict,
        current_time: datetime,
        article_index: int,
        total: int,
    ) -> Dict:
        params = {
            **static_params,
            **resolved_dynamic,
            'season': self._determine_season(current_time),
            'year': current_time.year,
            'current_year': current_time.year,
            'category': (
                self.template.blog_category.title
                if self.template.blog_category else
                self.schedule.category.title if self.schedule.category else 'Блог'
            ),
            'article_index': article_index + 1,
            'articles_per_run': total,
            'run_datetime': current_time.strftime('%d.%m.%Y %H:%M'),
            'run_date': current_time.strftime('%d.%m.%Y'),
        }

        params.update(self._enrich_weather_context(params, current_time))

        target_date = current_time + timedelta(days=1)
        formatted_date = f"{target_date.day} {MONTH_NAMES[target_date.month - 1]} {target_date.year}"
        params.setdefault('date', formatted_date)
        params.setdefault('weekday', WEEKDAY_NAMES[target_date.weekday()])

        if params.get('zodiac_sign'):
            params.setdefault('title', f"{params['zodiac_sign']} прогноз")
        else:
            params.setdefault('title', f"{self.schedule.name} прогноз")

        params.setdefault('topic', params.get('title') or self.schedule.name)
        self.context.add_log('debug', 'Parameters prepared', {'params': params})
        return params

    def _request_with_rate_limit(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        try:
            return self.client.chat(message=prompt, system_prompt=system_prompt)
        except Exception as exc:
            error_text = str(exc)
            if '429' in error_text or 'Too Many Requests' in error_text:
                raise self.RateLimitExceeded('GigaChat вернул 429 Too Many Requests')
            raise

    def _handle_rate_limit(
        self,
        errors: List[str],
        created_posts: List[Post],
        current_time: datetime,
        retry_after: int = 300,
    ) -> Dict:
        """
        РЕФАКТОРИНГ: обработка rate limit через сервисы из Test_Promot.
        """
        from Asistent.Test_Promot.services import (
            ScheduleTimestampService,
            ScheduleNotificationService
        )
        
        # РЕФАКТОРИНГ: переносим расписание через сервис
        next_run_time = ScheduleTimestampService.schedule_retry_after_rate_limit(
            schedule=self.schedule,
            current_time=current_time,
            retry_after_seconds=retry_after
        )

        self.context.add_log('warning', 'Rate limit encountered', {
            'retry_after_seconds': retry_after,
            'next_run': next_run_time.isoformat() if next_run_time else None,
        })

        # РЕФАКТОРИНГ: уведомления через сервис
        ScheduleNotificationService.send_notification(
            schedule=self.schedule,
            created_posts=created_posts if created_posts else None,
            success=False,
            error=f'GigaChat вернул 429 (Too Many Requests). Повтор через {retry_after // 60} мин.',
        )

        result = {
            'success': False,
            'status': 'partial',
            'schedule_id': self.schedule.id,
            'created_count': len(created_posts),
            'errors': errors,
            'retry_after_seconds': retry_after,
            'retry_scheduled_at': next_run_time.isoformat(),
        }
        self.context.set_result(**result)
        return result

    def _generate_content(self, params: Dict) -> Tuple[str, str, List[str], int]:
        content_type = self.template.content_source_type or 'generate'
        if content_type == 'hybrid':
            logger.info("      content_source_type=hybrid обнаружен, используем режим parse")
            content_type = 'parse'
        parsed_summary = ""
        source_urls_used: List[str] = []
        api_calls = 0

        if content_type == 'parse' and self.template.content_source_urls:
            urls = [u.strip() for u in self.template.content_source_urls.splitlines() if u.strip()]
            parsed_articles = []
            for url in urls[:3]:
                try:
                    result = self.parser.parse_article(url)
                    if result.get('success'):
                        parsed_articles.append({
                            'title': result.get('title', ''),
                            'text': result.get('text', '')[:777],
                            'url': url
                        })
                        source_urls_used.append(url)
                        logger.info("      📄 Источник: %s", result.get('title', 'Без названия')[:80])
                except Exception as exc:
                    logger.error("      ⚠️ Ошибка парсинга %s: %s", url, exc)

            if parsed_articles:
                parsed_summary = "\n\n".join(
                    f"Источник {idx+1}: {art['title']}\n{art['text'][:500]}..."
                    for idx, art in enumerate(parsed_articles)
                )
                rewrite_prompt = (
                    f"{self._build_prompt(params, params.get('weather_forecast'))}\n\n"
                    f"СПАРШЕННЫЙ КОНТЕНТ:\n{parsed_summary}\n\n"
                    "Перепиши этот контент своими словами, сохраняя факты и добавляя прогноз погоды."
                )
                api_calls += 1
                response = self._request_with_rate_limit(rewrite_prompt)
                return response, parsed_summary, source_urls_used, api_calls

            logger.warning("      ⚠️ Парсинг не удался, генерирую с нуля")

        api_calls += 1
        response = self._request_with_rate_limit(self._build_prompt(params, params.get('weather_forecast')))
        return response, parsed_summary, source_urls_used, api_calls

    
    def _postprocess_article(self, article_text: str, params: Dict) -> Tuple[str, str]:
        title_match = re.search(r'#\s*(.+)', article_text)
        if title_match:
            raw_title = title_match.group(1).strip()
            title = strip_tags(raw_title).strip()
            title = re.sub(r'[⭐☀️🌟☆💫☄️`*]+', '', title).strip()
            title = re.sub(r'\s+', ' ', title).strip()
            content_markdown = article_text.replace(title_match.group(0), '').strip()
        else:
            title = f"{params.get('topic', self.template.name)}"
            content_markdown = article_text

        content_html = render_markdown(content_markdown, preset=MarkdownPreset.CKEDITOR)

        sign = params.get('zodiac_sign')

        temp_post = Post(
            title=title,
            content=content_html,
            category=self.template.blog_category or self.schedule.category,
            author=self.ai_user
        )

        if 'faq-section' not in content_html.lower():
            faq_context = {'zodiac_sign': sign} if sign else None
            faq_result = self.optimizer.generate_faq_block(temp_post, context=faq_context)
            if faq_result.get('success') and faq_result.get('html'):
                content_html += '\n\n' + faq_result['html']

        if params.get('weather_forecast'):
            content_html += (
                "\n\n<p style=\"margin-top:1.5em; font-weight:500;\">"
                f"🌦️ Прогноз погоды: {params['weather_forecast']}"
                "</p>"
            )

        if sign:
            content_html = self._normalize_zodiac_content(content_html, sign)
            if sign.lower() not in title.lower():
                title = f"{sign}: {title}"

        return title, content_html

    def _create_post(
        self,
        title: str,
        content_html: str,
        params: Dict,
        target_category: Optional[Category] = None,
    ) -> Post:
        author = self.ai_user
        author_id = params.get('author_id')
        if author_id:
            try:
                selected_author = User.objects.get(id=author_id, is_active=True)
                author = selected_author
            except User.DoesNotExist:
                logger.warning("   ⚠️ Автор с ID %s не найден, используется AI-ассистент", author_id)

        category = target_category or self.template.blog_category or self.schedule.category
        if not category:
            category = Category.objects.order_by('id').first()

        payload = self._get_schedule_payload()
        publish_mode = str(payload.get('publish_mode') or 'published').strip().lower()
        status = 'draft' if publish_mode == 'draft' else 'published'
        auto_moderate = bool(payload.get('auto_moderate', True))
        moderation_status = 'pending' if auto_moderate else 'approved'
        plain_text_len = len(strip_tags(content_html or '').strip())
        min_words = max(int(self.schedule.min_word_count or 0), 0)
        approx_min_chars = min_words * 5 if min_words else 0
        moderation_note = ""
        if approx_min_chars and plain_text_len < approx_min_chars:
            status = 'draft'
            moderation_status = 'pending'
            moderation_note = (
                f"Quality gate: длина текста {plain_text_len} симв., "
                f"минимум по расписанию ~{approx_min_chars} симв."
            )

        description = ""
        description_template = payload.get('description_template')
        if description_template:
            try:
                description = str(description_template).format(**params)
            except Exception:
                description = ""
        if not description:
            description = strip_tags(content_html or '')[:200]

        partner_url = str(payload.get('partner_url') or '').strip()
        partner_link_text = str(payload.get('partner_link_text') or '').strip()
        if partner_url and partner_link_text and partner_url not in content_html:
            safe_link_text = partner_link_text.replace('<', '&lt;').replace('>', '&gt;')
            content_html += (
                "\n\n<p><a href=\"{url}\" target=\"_blank\" rel=\"nofollow sponsored noopener\">"
                "{text}</a></p>"
            ).format(url=partner_url, text=safe_link_text)

        post = Post(
            title=title,
            content=content_html,
            author=author,
            category=category,
            status=status,
            moderation_status=moderation_status,
            ai_moderation_notes=moderation_note,
            description=description,
            video_optimized=False,  # Гороскопы не используют видео
        )
        post._auto_generated_by_schedule = True
        post._auto_schedule_id = self.schedule.id
        post.save()
        return post

    def _get_schedule_payload(self) -> Dict:
        payload = self.schedule.payload_template or {}
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload) if payload.strip() else {}
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _select_target_category(self) -> Optional[Category]:
        """
        Выбирает категорию для article_single расписаний, если категория не задана явно.
        Логика ротации: берем категорию с самой старой датой последней публикации.
        """
        if self.template and self.template.blog_category:
            return self.template.blog_category

        if self.schedule.category:
            return self.schedule.category

        if (self.template and self.template.category != 'article_single') or self.schedule.task_type != 'generate_article':
            return None

        categories = (
            Category.objects
            .annotate(
                last_post_created=Max(
                    'posts__created',
                    filter=Q(posts__status='published'),
                )
            )
            .order_by('last_post_created', 'id')
        )
        category = categories.first()
        if category:
            self.context.add_log('info', 'Category selected by rotator', {
                'category_id': category.id,
                'category_title': category.title,
                'last_post_created': category.last_post_created.isoformat() if category.last_post_created else None,
            })
        return category

    def _apply_tags(self, post: Post, params: Dict) -> None:
        if not self.template.tags_criteria:
            return

        tags_raw = self.template.tags_criteria.split(',')
        tags_resolved = []
        for item in tags_raw:
            item = item.strip()
            if not item:
                continue
            if item.startswith('"') and item.endswith('"'):
                tags_resolved.append(item.strip('"'))
            elif item.startswith('{') and item.endswith('}'):
                var_name = item.strip('{}')
                tags_resolved.append(params.get(var_name, ''))
            else:
                tags_resolved.append(params.get(item, item))

        valid_tags = [str(tag).strip() for tag in tags_resolved if str(tag).strip()]
        for tag in valid_tags:
            post.tags.add(tag)

    def _generate_image(self, params: Dict, title: str) -> Tuple[Optional[str], str]:
        image_type = self.template.image_source_type or 'generate_auto'
        image_path = None
        image_info = "Не генерировалось"
        weather_hint = params.get('weather_forecast', '')

        if image_type in ('generate_custom', 'generate_auto'):
            try:
                if image_type == 'generate_custom' and self.template.image_generation_criteria:
                    image_prompt = self.template.image_generation_criteria.format(**params)
                else:
                    image_prompt = f"Стильное изображение для статьи: {title}"

                if weather_hint:
                    image_prompt += f". Погода: {weather_hint}"

                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    image_path = loop.run_until_complete(
                        self.client.generate_and_save_image(prompt=image_prompt)
                    )
                finally:
                    loop.close()

                if image_path:
                    image_info = f"Сгенерировано: {image_path}"
                    logger.info("      🖼️ Изображение создано: %s", image_path)
                else:
                    image_info = "Ошибка: пустой путь"
            except RateLimitCooldown as cooldown_error:
                logger.warning("      ⏸️ GigaChat в cooldown: %s", cooldown_error)
                raise self.RateLimitExceeded(str(cooldown_error), retry_after=cooldown_error.retry_after)
            except Exception as exc:
                logger.error("      ❌ Ошибка генерации изображения: %s", exc, exc_info=True)
                image_info = f"Ошибка генерации: {exc}"

        elif image_type == 'parse_web':
            urls = []
            if self.template.content_source_urls:
                urls = [u.strip() for u in self.template.content_source_urls.splitlines() if u.strip()]
            found = None
            for url in urls[:3]:
                try:
                    result = self.parser.parse_article(url)
                    if result.get('success') and result.get('downloaded_images'):
                        found = result['downloaded_images'][0]
                        break
                except Exception as exc:
                    logger.error("      ⚠️ Ошибка парсинга изображения из %s: %s", url, exc)
            if found:
                image_path = found
                image_info = f"Спаршено из {url}"
            else:
                image_info = "Парсинг не удался, изображения не найдены"

        elif image_type == 'search_db':
            from django.db.models import Q
            search_keywords = self.template.image_search_criteria.format(**params) if self.template.image_search_criteria else title
            words = search_keywords.split()
            if words:
                similar_posts = Post.objects.filter(
                    Q(title__icontains=words[0]) | Q(content__icontains=words[0]),
                    kartinka__isnull=False
                ).exclude(kartinka='')[:5]
                if similar_posts.exists():
                    first_post = similar_posts.first()
                    image_path = first_post.kartinka.name if hasattr(first_post.kartinka, 'name') else str(first_post.kartinka)
                    image_info = f"Найдено в базе: {image_path}"
                else:
                    image_info = "В базе не найдено подходящих изображений"

        elif image_type == 'upload' and self.template.uploaded_media:
            image_path = self.template.uploaded_media.name
            image_info = f"Загружено модератором: {image_path}"

        elif image_type == 'none':
            image_path = 'images/logo/idealimage_logo.webp'
            image_info = "Используется логотип сайта"

        return image_path, image_info

    def _normalize_zodiac_content(self, text: str, zodiac_sign: Optional[str]) -> str:
        if not text or not zodiac_sign:
            return text

        normalized = text
        sign_lower = zodiac_sign.lower()

        for other in ZODIAC_SIGNS:
            if other.lower() == sign_lower:
                continue
            pattern = re.compile(rf'\b{re.escape(other)}\b', re.IGNORECASE)
            normalized = pattern.sub(zodiac_sign, normalized)

        return normalized

    def _update_schedule_timestamps(self, current_time: datetime) -> None:
        self.schedule.current_run_count += 1
        if self.schedule.max_runs and self.schedule.current_run_count >= self.schedule.max_runs:
            self.schedule.is_active = False
            logger.info("   🛑 Достигнут лимит запусков (%s). Расписание деактивировано.", self.schedule.max_runs)

        self.schedule.last_run = current_time
        # Для интервальных расписаний используем interval_minutes, для остальных - posting_frequency
        if self.schedule.schedule_kind == 'interval' and self.schedule.interval_minutes:
            next_run_delta = timedelta(minutes=self.schedule.interval_minutes)
        else:
            next_run_delta = calculate_next_run_delta(self.schedule.posting_frequency)
        self.schedule.next_run = current_time + next_run_delta
        self.schedule.save(update_fields=['last_run', 'next_run', 'current_run_count', 'is_active'])

    # -- static helpers ---------------------------------------------------------

    @staticmethod
    def _determine_season(dt: datetime) -> str:
        month = dt.month
        if month in (12, 1, 2):
            return 'зима'
        if month in (3, 4, 5):
            return 'весна'
        if month in (6, 7, 8):
            return 'лето'
        return 'осень'

    def _get_or_create_ai_user(self) -> User:
        ai_user, _ = User.objects.get_or_create(
            username='ai_assistant',
            defaults={
                'first_name': 'AI',
                'last_name': 'Ассистент',
                'email': 'ai@idealimage.ru',
                'is_active': True
            }
        )
        return ai_user

    def _enrich_weather_context(self, params: Dict, current_dt: datetime) -> Dict:
        city = params.get('weather_city') or params.get('city') or params.get('город')
        if not city:
            return {}

        api_key = getattr(settings, 'OPENWEATHER_API_KEY', '')
        if not api_key:
            logger.warning("   🌦️ OPENWEATHER_API_KEY не задан, пропускаю прогноз погоды")
            return {}

        forecast_url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?q={city}&units=metric&lang=ru&appid={api_key}"
        )

        try:
            response = requests.get(forecast_url, timeout=10)
            if response.status_code != 200:
                logger.warning("   🌦️ Не удалось получить прогноз (%s)", response.status_code)
                return {}

            data = response.json()
            if not data.get('list'):
                return {}

            target_date = (current_dt + timedelta(days=1)).date()
            selected = None

            for entry in data['list']:
                dt_txt = entry.get('dt_txt')
                if not dt_txt:
                    continue
                entry_dt = datetime.strptime(dt_txt, '%Y-%m-%d %H:%M:%S')
                if entry_dt.date() == target_date and entry_dt.hour in (9, 12, 15):
                    selected = entry
                    break

            if not selected:
                selected = data['list'][0]

            temp = selected['main'].get('temp')
            feels_like = selected['main'].get('feels_like')
            description = selected['weather'][0].get('description', '').capitalize()
            wind = selected.get('wind', {}).get('speed')

            weather_text = (
                f"По прогнозу на завтра в городе {city} ожидается {description.lower()} "
                f"с температурой около {round(temp)}°C"
            )
            if feels_like is not None:
                weather_text += f", ощущается как {round(feels_like)}°C"
            if wind is not None:
                weather_text += f". Ветер — примерно {round(wind)} м/с"
            weather_text += ". Не забудьте учесть погоду при планах!"

            logger.info("   🌦️ Прогноз погоды: %s", weather_text)

            return {
                'weather_forecast': weather_text,
                'weather_temp': temp,
                'weather_description': description,
                'weather_wind': wind,
                'weather_city': city,
            }
        except Exception as exc:
            logger.error("   🌦️ Ошибка получения погоды: %s", exc)
            return {}

    def _build_prompt(self, params: Dict, weather_text: Optional[str]) -> str:
        title_instructions = self.template.title_criteria.format(**params) if self.template.title_criteria else ""
        prompt_parts = []
        if title_instructions:
            prompt_parts.append(title_instructions)
        prompt_parts.append(self.template.template.format(**params))

        if weather_text:
            prompt_parts.append(
                "\n\nДополнительная информация для статьи:\n"
                f"ПРОГНОЗ ПОГОДЫ: {weather_text}\n"
                "Используй этот прогноз, чтобы добавить советы и атмосферу в статье. "
            )
        return "\n\n---\n\n".join(prompt_parts)

"""Выполнение системных задач расписаний"""
class SystemTaskRunner:
    """Выполнение системных задач расписаний."""

    def __init__(self, schedule: AISchedule, context: ScheduleContext):
        self.schedule = schedule
        self.context = context

    def run(self, current_time: datetime) -> Dict:
        task_name = self.schedule.strategy_options.get('task') if self.schedule.strategy_options else None
        if not task_name:
            task_name = self.schedule.static_params.get('task') if self.schedule.static_params else None
        if not task_name:
            raise ValueError("Для системной стратегии необходимо указать название задачи")

        result = self._execute_task(task_name, current_time)

        self.schedule.last_run = current_time
        # Для интервальных расписаний используем interval_minutes, для остальных - posting_frequency
        if self.schedule.schedule_kind == 'interval' and self.schedule.interval_minutes:
            next_run_delta = timedelta(minutes=self.schedule.interval_minutes)
        else:
            next_run_delta = calculate_next_run_delta(self.schedule.posting_frequency)
        self.schedule.next_run = current_time + next_run_delta
        self.schedule.save(update_fields=['last_run', 'next_run'])

        self.context.set_result(**result)
        return result

    def _execute_task(self, task_name: str, now: datetime) -> Dict:
        logger.info("   ⚙️ Запуск системной задачи: %s", task_name)
        if task_name == 'optimization':
            seo_result = auto_seo_optimize_new_articles()
            submit_result = submit_new_posts_to_search_engines()
            return {
                'success': True,
                'status': 'success',
                'seo_optimized': seo_result.get('optimized', 0),
                'submitted_to_search': submit_result.get('submitted', 0),
                'created_count': 0,
                'errors': [],
            }
        if task_name == 'process_images':
            images_result = bulk_media_images_indexing()
            return {
                'success': True,
                'status': 'success',
                'images_indexed': images_result.get('indexed', 0),
                'created_count': 0,
                'errors': [],
            }
        if task_name == 'add_faq':
            return run_faq_extension_workflow(now)

        raise ValueError(f"Неизвестная системная задача: {task_name}")


"""Ручной режим (задачи администратора без автоматических действий)"""
class ManualWorkflow:
    """Ручной режим (задачи администратора без автоматических действий)."""

    def __init__(self, schedule: AISchedule, context: ScheduleContext):
        self.schedule = schedule
        self.context = context

    def run(self, current_time: datetime) -> Dict:
        # Ручной режим пока просто фиксирует факт запуска
        self.schedule.last_run = current_time
        self.schedule.next_run = None
        self.schedule.save(update_fields=['last_run', 'next_run'])
        result = {
            'success': True,
            'status': 'success',
            'created_count': 0,
            'message': 'Ручной запуск зафиксирован. Никаких автоматических действий не выполнялось.',
        }
        self.context.set_result(**result)
        return result


# ------------------------------------------------------------------------------
# Функции, переиспользующие прежние задачи.
# ------------------------------------------------------------------------------

"""Вычисление интервала до следующего запуска на основе частоты"""
def calculate_next_run_delta(frequency: str) -> timedelta:
    frequency_map = {
        'daily': timedelta(days=1),
        'weekly': timedelta(weeks=1),
        'biweekly': timedelta(weeks=2),
        'monthly': timedelta(days=30),
    }
    return frequency_map.get(frequency, timedelta(days=1))

"""Отправка уведомления в Telegram о результатах выполнения расписания"""
def send_schedule_notification(schedule: AISchedule, created_posts: Optional[List[Post]], success: bool = True, error: Optional[str] = None, skip_if_no_posts: bool = False, skip_daily_limit: bool = False) -> None:
    if not schedule:
        return

    chat_id = getattr(settings, 'CHAT_ID8', None)
    if not chat_id:
        return

    posts_count = len(created_posts) if created_posts else 0
    
    # Пропускаем уведомление если достигнут дневной лимит (это нормальная ситуация)
    if skip_daily_limit:
        logger.debug("Пропуск уведомления: достигнут дневной лимит для расписания %s", schedule.id)
        return
    
    # Пропускаем уведомление если успешно выполнено но ничего не создано (без ошибок)
    if success and posts_count == 0 and skip_if_no_posts:
        logger.debug("Пропуск уведомления: успешно выполнено, но статей не создано для расписания %s", schedule.id)
        return
    
    # Пропускаем уведомление если успешно выполнено но ничего не создано И нет ошибки
    # (это может быть нормальная ситуация - например, все уже создано)
    if success and posts_count == 0 and not error:
        logger.debug("Пропуск уведомления: успешно выполнено без создания статей и без ошибок для расписания %s", schedule.id)
        return

    if success:
        emoji = "✅" if posts_count > 0 else "⚠️"
        text = (
            f"{emoji} <b>AI-расписание выполнено</b>\n\n"
            f"📋 Расписание: {schedule.name}\n"
            f"📁 Категория: {schedule.category.title if schedule.category else 'Не указана'}\n"
            f"📊 Создано статей: {posts_count}\n"
            f"⏰ Следующий запуск: {schedule.next_run.strftime('%d.%m.%Y %H:%M') if schedule.next_run else '—'}"
        )
    else:
        # Проверяем, не является ли это дневным лимитом (не отправляем как ошибку)
        if error and "daily_limit_reached" in error.lower():
            logger.debug("Пропуск уведомления: достигнут дневной лимит (не ошибка) для расписания %s", schedule.id)
            return
            
        text = (
            f"❌ <b>Ошибка AI-расписания</b>\n\n"
            f"📋 Расписание: {schedule.name}\n"
            f"🔴 Ошибка: {error[:200] if error else 'Неизвестная ошибка'}\n\n"
            "Проверьте логи для подробностей."
        )

    client = get_telegram_client()
    if not client.send_message(chat_id, text, parse_mode="HTML"):
        logger.warning("Не удалось отправить уведомление в Telegram для расписания %s", schedule.id)


# ------------------------------------------------------------------------------
# Импортируемые ранее системные задачи (оптимизация, индексация, FAQ и т.п.)
# ------------------------------------------------------------------------------

"""Отправка новых статей в поисковые системы"""
def submit_new_posts_to_search_engines():
    """
    Отправка новых статей в поисковые системы.
    Перенесено из Asistent.tasks для унифицированного доступа.
    """
    try:
        recent_posts = Post.objects.filter(
            status='published',
            created__gte=timezone.now() - timedelta(hours=2)
        )

        if not recent_posts.exists():
            logger.info("ℹ️ Нет новых статей для отправки")
            return {'success': True, 'submitted': 0}

        submitted_count = 0

        for post in recent_posts:
            try:
                result = submit_post_for_indexing(post.id)
                if result:
                    submitted_count += 1
            except Exception as e:
                logger.error("❌ Ошибка отправки %s: %s", post.id, e)
                continue

        logger.info("✅ Отправлено статей: %s", submitted_count)
        return {'success': True, 'submitted': submitted_count}

    except Exception as e:
        logger.error("❌ Ошибка в submit_new_posts_to_search_engines: %s", e)
        return {'success': False, 'error': str(e)}

"""Асинхронная индексация статьи"""
def submit_post_for_indexing(post_id: int):
    """
    Асинхронная индексация статьи.
    Возвращает словарь результатов, совпадающий со старой функцией.
    """
    try:
        post = Post.objects.get(id=post_id, status='published')
        post_url = f"{settings.SITE_URL.rstrip('/')}{post.get_absolute_url()}"

        results = {k: False for k in ['yandex', 'google', 'bing', 'yahoo', 'indexnow']}

        try:
            client = get_yandex_webmaster_client()
            yandex_result = client.enqueue_recrawl(post_url)
            results['yandex'] = bool(yandex_result.get('success'))
            if not results['yandex']:
                logger.error("Яндекс индексация: %s", yandex_result.get('error'))
        except Exception as e:
            logger.error("Яндекс индексация: %s", e)

        try:
            sitemap_url = f"{settings.SITE_URL}/sitemap.xml"
            ping_url = f"https://www.google.com/ping?sitemap={sitemap_url}"
            resp = requests.get(ping_url, timeout=10)
            results['google'] = resp.status_code == 200
        except Exception as e:
            logger.error("Google: %s", e)

        for key_name, api_url, result_key in [
            ('BING_INDEXNOW_KEY', 'https://www.bing.com/indexnow', 'bing'),
            ('INDEXNOW_KEY', 'https://api.indexnow.org/indexnow', 'indexnow')
        ]:
            try:
                if hasattr(settings, key_name):
                    key = getattr(settings, key_name)
                    payload = {
                        "host": settings.SITE_URL.replace('https://', '').replace('http://', ''),
                        "key": key,
                        "urlList": [post_url]
                    }
                    if key_name == 'INDEXNOW_KEY':
                        payload["keyLocation"] = f"{settings.SITE_URL}/{key}.txt"
                    resp = requests.post(api_url, json=payload, timeout=10)
                    results[result_key] = resp.status_code == 200
            except Exception as e:
                logger.error("%s: %s", result_key, e)

        results['yahoo'] = results['bing'] or results['indexnow']
        logger.info("Индексация %s: %s", post_url, results)
        return results

    except Post.DoesNotExist:
        logger.error("Post %s не найден", post_id)
        return None
    except Exception as e:
        logger.error("Ошибка индексации: %s", e, exc_info=True)
        return None

"""Автоматическая SEO-оптимизация новых статей"""
def auto_seo_optimize_new_articles():
    """
    Автоматическая SEO-оптимизация новых статей.
    """
    try:
        recent_posts = Post.objects.filter(
            status='published',
            created__gte=timezone.now() - timedelta(hours=6)
        )

        if not recent_posts.exists():
            logger.info("ℹ️ Нет новых статей для оптимизации")
            return {'success': True, 'optimized': 0}

        total = recent_posts.count()
        logger.info(
            "⚠️ Автоматическая SEO-оптимизация пропущена: analyzer/optimizer недоступны "
            "(AdvancedSEOOptimizer.analyze_seo/optimize_seo не реализованы)."
        )

        for post in recent_posts:
            logger.debug("Пропуск SEO-оптимизации для статьи: %s", post.title)

        return {
            'success': True,
            'optimized': 0,
            'total': total,
            'skipped': True,
            'reason': 'seo_analyzer_not_available'
        }

    except Exception as e:
        logger.error("❌ Ошибка в auto_seo_optimize_new_articles: %s", e)
        return {'success': False, 'error': str(e)}

"""Поэтапная индексация изображений из MEDIA папки"""
def bulk_media_images_indexing():
    """
    Поэтапная индексация изображений из MEDIA папки.
    """
    import os
    from pathlib import Path

    logger.info("🖼️ Запуск индексации изображений MEDIA")

    try:
        media_path = Path(settings.MEDIA_ROOT) / 'images'

        if not media_path.exists():
            logger.warning("⚠️ Папка media/images не найдена")
            return {'success': False, 'error': 'media_path_not_found'}

        image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif'}
        image_urls: List[str] = []

        for root, _, files in os.walk(media_path):
            for file in files:
                if Path(file).suffix.lower() in image_extensions:
                    relative_path = Path(root).relative_to(settings.MEDIA_ROOT)
                    image_url = f"{settings.SITE_URL.rstrip('/')}/media/{relative_path}/{file}"
                    image_urls.append(image_url)

                    if len(image_urls) >= 100:
                        break

            if len(image_urls) >= 100:
                break

        if not image_urls:
            logger.info("ℹ️ Нет изображений для индексации")
            return {'success': True, 'indexed': 0}

        result = submit_images_to_search_engines(image_urls)

        logger.info("✅ Отправлено изображений: %s", len(image_urls))
        return {
            'success': True,
            'indexed': len(image_urls),
            'indexnow': result.get('indexnow', {}).get('success', False)
        }

    except Exception as e:
        logger.error("❌ Ошибка в bulk_media_images_indexing: %s", e)
        return {'success': False, 'error': str(e)}

"""Отправка изображений в IndexNow"""
def submit_images_to_search_engines(image_urls: List[str]) -> Dict:
    """
    Вынесенная вспомогательная функция (ранее часть seo_advanced). 
    Сейчас упрощенная отправка через IndexNow.
    """
    try:
        if not hasattr(settings, 'INDEXNOW_KEY'):
            return {'success': False, 'reason': 'INDEXNOW_KEY not set'}

        api_url = "https://api.indexnow.org/indexnow"
        payload = {
            "host": settings.SITE_URL.replace('https://', '').replace('http://', '').rstrip('/'),
            "key": settings.INDEXNOW_KEY,
            "keyLocation": f"{settings.SITE_URL.rstrip('/')}/indexnow-{settings.INDEXNOW_KEY}.txt",
            "urlList": image_urls
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        success = response.status_code in [200, 202]
        return {'success': success, 'status': response.status_code, 'indexnow': {'success': success}}
    except Exception as e:
        logger.warning("⚠️ Ошибка отправки изображений в IndexNow: %s", e)
        return {'success': False, 'error': str(e)}

"""Выполнение ветки add_faq из прежнего run_system_task"""
def run_faq_extension_workflow(now: datetime) -> Dict:
    """
    Логика ветки add_faq из прежнего run_system_task.
    Вынесена отдельно, чтобы сократить зависимости.
    """
    from Asistent.gigachat_api import get_gigachat_client
    from Asistent.seo_advanced import AdvancedSEOOptimizer
    from blog.models import Post

    optimizer = AdvancedSEOOptimizer()
    gigachat_client = get_gigachat_client()

    old_posts_qs = Post.objects.filter(
        status='published',
        created__lt=timezone.now() - timedelta(days=7)
    ).exclude(
        content__icontains='faq-section'
    )[:100]

    faq_added = 0
    extended_count = 0

    for post in old_posts_qs:
        try:
            original_content = post.content

            sign_guess = next((z for z in ZODIAC_SIGNS if z.lower() in post.title.lower()), None)
            faq_context = {'zodiac_sign': sign_guess} if sign_guess else None
            faq_result = optimizer.generate_faq_block(post, context=faq_context)
            if faq_result.get('success') and faq_result.get('questions'):
                post.content = f"{post.content}\n\n{faq_result['html']}"
                faq_added += 1

            words_count = len(strip_tags(post.content).split())
            if words_count < 600:
                try:
                    extend_prompt = (
                        "Расширь приведённый текст статьи до 600-650 слов, сохраняя стиль, факты и структуру. "
                        "Добавь полезные советы и интересные детали. Ответ верни в формате Markdown без верхнего заголовка.\n\n"
                        f"{strip_tags(post.content)}"
                    )
                    extension_text = gigachat_client.chat(message=extend_prompt)
                    if extension_text:
                        post.content = render_markdown(extension_text, preset=MarkdownPreset.CKEDITOR)
                        extended_count += 1
                        logger.info("   ✍️ Текст расширен до 600+ слов: %s", post.title[:60])
                except Exception as extend_exc:
                    logger.error("   ⚠️ Ошибка догенерации текста для %s: %s", post.id, extend_exc)
                    post.content = original_content

            post.save()
            logger.info("   ✅ Обработана статья: %s", post.title[:60])
        except Exception as e:
            logger.error("   ❌ Ошибка обработки %s: %s", post.id, e)

    return {
        'success': True,
        'status': 'success',
        'faq_added': faq_added,
        'extended': extended_count,
        'processed': old_posts_qs.count(),
        'created_count': 0,
        'errors': [],
    }

