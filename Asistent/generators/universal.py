"""
УНИВЕРСАЛЬНЫЙ ГЕНЕРАТОР КОНТЕНТА

Объединяет лучшее из трёх систем:
- Test_Promot (модульная архитектура, сервисы)
- tasks.py (очереди, heartbeat, приоритизация, метрики)
- schedule (интеграция с расписаниями)

Режимы работы:
- AUTO: Полная автоматизация с очередями
- INTERACTIVE: Ручной запуск с предпросмотром
- BATCH: Массовая генерация
- SCHEDULED: Через систему schedule
"""

import json
import logging
import re
import time
from typing import Dict, List, Optional
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.utils.html import strip_tags
from django.contrib.auth.models import User

from Asistent.models import PromptTemplate
from Asistent.Test_Promot.services import (
    ContentGenerationFactory,
    TitleGenerator,
    ImageProcessor,
    TagProcessor,
)
from Asistent.Test_Promot.test_prompt import render_template_text, _convert_markdown_to_html
from Asistent.gigachat_api import get_gigachat_client, RateLimitCooldown
from blog.models import Post, Category

from .base import GeneratorMode, GeneratorConfig, GenerationResult
from .context import UniversalContextBuilder
from .queue import QueueManager
from .heartbeat import HeartbeatManager
from .metrics import MetricsTracker

logger = logging.getLogger(__name__)

# Общие инструкции для генерации статей (стилистика, запреты) — не дублировать в каждом промпте
DEFAULT_SYSTEM_PROMPT = (
    'Пиши экспертно и дружелюбно. Избегай канцелярита и воды. '
    'Не используй слова: «данный», «является», «осуществлять», «в рамках».'
)

# Quality Gate (ТЗ №4): минимум символов для публикации
MIN_TEXT_PUBLISH = 2000
MIN_TEXT_HOROSCOPE = 800  # Гороскопы короче по жанру

# Паттерны отказных сообщений GigaChat (контентная политика)
GIGACHAT_REFUSAL_PATTERNS = [
    'временно ограничены',
    'не могу создать',
    'не могу написать',
    'противоречит правилам',
    'чувствительными темами',
    'не могу помочь с этим',
    'нарушает правила',
]
QUALITY_GATE_NEEDS_EDIT = 'Нужна ручная правка: текст или изображение не прошли проверку.'


class UniversalContentGenerator:
    """
    УНИВЕРСАЛЬНЫЙ ГЕНЕРАТОР КОНТЕНТА.
    
    Примеры использования:
    
    # Автоматический режим (как tasks.py)
    config = GeneratorConfig.for_auto()
    generator = UniversalContentGenerator(template, config, schedule_id=123)
    result = generator.generate(schedule_payload={'zodiac_sign': 'Овен'})
    
    # Интерактивный режим (как test_prompt.py)
    config = GeneratorConfig.for_interactive()
    generator = UniversalContentGenerator(template, config)
    result = generator.generate(variables={'category': 'здоровье'})
    
    # Через schedule
    config = GeneratorConfig.for_scheduled()
    generator = UniversalContentGenerator(template, config, schedule_id=456)
    result = generator.generate(schedule_payload={...})
    """
    
    def __init__(
        self,
        template: PromptTemplate,
        config: GeneratorConfig = None,
        schedule_id: Optional[int] = None
    ):
        """
        Args:
            template: Шаблон промпта
            config: Конфигурация генератора (по умолчанию INTERACTIVE)
            schedule_id: ID расписания (для AUTO/SCHEDULED режимов)
        """
        self.template = template
        self.config = config or GeneratorConfig.for_interactive()
        self.schedule_id = schedule_id
        
        # Компоненты (ленивая инициализация)
        self._queue_manager: Optional[QueueManager] = None
        self._heartbeat: Optional[HeartbeatManager] = None
        self._metrics: Optional[MetricsTracker] = None
        self._context_builder: Optional[UniversalContextBuilder] = None
        self._client = None
        
        logger.info(
            f"🎨 UniversalContentGenerator инициализирован "
            f"(режим: {self.config.mode.value}, шаблон: {template.name})"
        )
    
    def generate(
        self,
        variables: Dict = None,
        schedule_payload: Dict = None
    ) -> GenerationResult:
        """
        ГЛАВНЫЙ МЕТОД ГЕНЕРАЦИИ КОНТЕНТА.
        
        Args:
            variables: Переменные из формы (для INTERACTIVE)
            schedule_payload: Параметры из расписания (для SCHEDULED/AUTO)
        
        Returns:
            GenerationResult с результатом генерации
        """
        try:
            # 1. Инициализация компонентов
            self._initialize_components()
            
            # 2. Проверка дневного лимита удалена - не используется
            
            # 3. Добавление в очередь (только AUTO)
            if self.config.use_queue and self.schedule_id:
                if not self._enter_queue():
                    return GenerationResult(
                        success=False,
                        error='queue_timeout'
                    )
            
            # 4. Подготовка контекста
            context = self._build_context(variables, schedule_payload)
            
            # 5. Генерация контента
            content_result = self._generate_content(context)
            
            # 6. Генерация изображения
            image_result = self._generate_image(context)
            
            # 7. Публикация или предпросмотр
            if self.config.preview_only:
                result = self._save_to_session(content_result, image_result, context)
            else:
                post = self._publish_post(content_result, image_result, context)
                
                # 8. Метрики
                if self.config.use_metrics and self._metrics:
                    self._metrics.save_to_database(
                        post=post,
                        prompt_text=content_result.get('prompt', ''),
                        ai_response=content_result.get('plain_text', ''),
                    )
                    self._metrics.log_summary()
                
                result = GenerationResult(
                    success=True,
                    post=post,
                    post_id=post.id,
                    title=post.title,
                    content=post.content,
                    image_path=str(post.kartinka) if post.kartinka else None,
                    metrics=self._metrics.get_data() if self._metrics else {}
                )
            
            logger.info(f"✅ Генерация завершена успешно (post_id: {result.post_id})")
            return result
        
        except ValueError as e:
            if 'no_image_after_fallback' in str(e):
                logger.error("🚫 Генерация отменена: нет изображения. Черновик не создаётся.")
                return GenerationResult(
                    success=False,
                    error='no_image_after_fallback',
                )
            logger.exception(f"❌ Ошибка генерации: {e}")
            return GenerationResult(success=False, error=str(e))

        except RateLimitCooldown as e:
            logger.warning(f"⏸️ Rate limit: {e}")
            return GenerationResult(
                success=False,
                error=f'rate_limit: {str(e)}'
            )
        
        except Exception as e:
            logger.exception(f"❌ Ошибка генерации: {e}")
            return GenerationResult(
                success=False,
                error=str(e)
            )
        
        finally:
            # Очистка
            self._cleanup()
    
    def _initialize_components(self):
        """Инициализация компонентов"""
        logger.debug("   🔧 Инициализация компонентов")
        
        if self.config.use_queue and self.schedule_id:
            queue_name = f"{self.template.category or 'content'}_generation"
            self._queue_manager = QueueManager(queue_name=queue_name)
        
        if self.config.use_heartbeat and self.schedule_id:
            self._heartbeat = HeartbeatManager(self.schedule_id)
            self._heartbeat.start()
        
        if self.config.use_metrics:
            self._metrics = MetricsTracker()
        
        self._context_builder = UniversalContextBuilder(
            template=self.template,
            user_variables={},
            mode=self.config.mode
        )
        
        self._client = get_gigachat_client()
    
    
    def _enter_queue(self) -> bool:
        """
        Добавление в очередь и ожидание.
        
        Returns:
            True если успешно вошли в очередь, False если таймаут
        """
        if not self._queue_manager or not self.schedule_id:
            return True
        
        position = self._queue_manager.add_to_queue(self.schedule_id)
        if self._metrics:
            self._metrics.record_queue_position(position)
        
        success = self._queue_manager.wait_for_turn(self.schedule_id, max_wait=3600)
        
        if not success:
            logger.error(f"   ❌ Таймаут ожидания очереди")
        
        return success
    
    def _build_context(self, variables: Dict, schedule_payload: Dict) -> Dict:
        """
        Построение контекста переменных.
        
        Args:
            variables: Переменные из формы
            schedule_payload: Параметры из расписания
        
        Returns:
            Полный контекст переменных
        """
        logger.debug("   📝 Построение контекста")
        
        # Обновляем heartbeat
        if self._heartbeat:
            self._heartbeat.update()
        
        # Объединяем переменные
        self._context_builder.user_variables = variables or {}
        context = self._context_builder.build(schedule_payload)
        
        return context
    
    def _generate_content(self, context: Dict) -> Dict:
        """
        Генерация текстового контента.
        
        Args:
            context: Контекст переменных
        
        Returns:
            Словарь с результатом (title, content, plain_text, prompt)
        """
        logger.info("   📄 Генерация текста...")
        
        # Обновляем heartbeat
        if self._heartbeat:
            self._heartbeat.update()
        
        # Рендерим промпт
        article_prompt = render_template_text(self.template.template or '', context)
        
        if not article_prompt.strip():
            raise ValueError('Промпт пустой после рендеринга')
        
        # Системный промпт (общие инструкции — экономия токенов)
        context['_system_prompt'] = self._get_system_prompt()
        
        # Генерация через ContentGenerationFactory (из Test_Promot)
        strategy = ContentGenerationFactory.create_strategy(
            self.template,
            self._client,
            self.config.timeout,
            context=context  # Передаем контекст для автоматического формирования URL гороскопов
        )
        
        # Генерация с retry
        article_text, source_info, parsed_content = self._generate_with_retry(
            strategy, article_prompt, context
        )
        
        # Детектор отказного сообщения GigaChat (контентная политика)
        text_lower = article_text.lower()
        if any(pattern in text_lower for pattern in GIGACHAT_REFUSAL_PATTERNS):
            logger.warning(
                "   ⚠️ GigaChat вернул отказное сообщение. "
                "Используем спаршенный контент напрямую."
            )
            article_text = parsed_content or article_text

        # Генерация заголовка
        title_generator = TitleGenerator(
            self.template, self._client, self.config.timeout
        )
        title = title_generator.generate(
            context, article_text, context.get('title', '')
        )
        
        # Обновляем heartbeat
        if self._heartbeat:
            self._heartbeat.update()
        
        # Конвертация Markdown → HTML
        content_html = _convert_markdown_to_html(article_text)
        
        # FAQ по тексту статьи (для гороскопов можно отключить для экономии токенов)
        disable_faq = bool(context.get('disable_faq', False))
        faq_list = []
        if disable_faq:
            logger.info("   ⏭️ FAQ отключен настройкой контекста")
        else:
            faq_list = self._generate_faq(article_text)
            if faq_list:
                content_html += self._format_faq_html(faq_list)
                logger.info(f"   ✅ Добавлен блок FAQ: {len(faq_list)} вопросов")
        
        logger.info(f"   ✅ Текст сгенерирован (длина: {len(article_text)} символов)")
        
        return {
            'title': title,
            'content': content_html,
            'plain_text': article_text,
            'source_info': source_info,
            'prompt': article_prompt,
            'parsed_content': parsed_content,
            'faq': faq_list if faq_list else None,
        }
    
    def _generate_with_retry(self, strategy, prompt: str, context: Dict) -> tuple:
        """
        Генерация с retry механизмом.
        
        Args:
            strategy: Стратегия генерации
            prompt: Текст промпта
            context: Контекст переменных
        
        Returns:
            (article_text, source_info, parsed_content)
        """
        parsed_content = None
        for attempt in range(self.config.retry_count):
            try:
                if self._metrics:
                    self._metrics.record_api_call()
                
                result = strategy.generate(prompt, context)
                # Обрабатываем разные форматы возврата (для обратной совместимости)
                if len(result) == 3:
                    article_text, source_info, parsed_content = result
                else:
                    article_text, source_info = result
                    parsed_content = None
                
                if article_text and article_text.strip():
                    return article_text, source_info, parsed_content
                
                logger.warning(f"   ⚠️ Пустой ответ (попытка {attempt + 1}/{self.config.retry_count})")
                
            except RateLimitCooldown as e:
                if self._metrics:
                    self._metrics.record_error(f'RateLimitCooldown: {str(e)}')
                    self._metrics.record_retry()
                
                if attempt < self.config.retry_count - 1:
                    wait_time = getattr(e, 'retry_after', 60)
                    logger.warning(f"   ⏸️ Rate limit, ожидание {wait_time} сек...")
                    time.sleep(wait_time)
                    
                    if self._heartbeat:
                        self._heartbeat.update(force=True)
                else:
                    raise
            
            except Exception as e:
                if self._metrics:
                    self._metrics.record_error(f'Exception: {str(e)}')
                    self._metrics.record_retry()
                
                if attempt < self.config.retry_count - 1:
                    wait_time = 5 * (attempt + 1)
                    logger.warning(f"   ⚠️ Ошибка, повтор через {wait_time} сек: {e}")
                    time.sleep(wait_time)
                else:
                    raise
        
        raise ValueError('Не удалось сгенерировать текст после всех попыток')
    
    def _get_system_prompt(self) -> str:
        """Общие инструкции для GigaChat (из настроек или константа). Не дублируются в каждом запросе."""
        return getattr(settings, 'GIGACHAT_ARTICLE_SYSTEM_PROMPT', None) or DEFAULT_SYSTEM_PROMPT
    
    def _generate_faq(self, article_plain_text: str) -> List[Dict]:
        """
        Генерация 3 вопросов и ответов по статье. ТЗ №3, подготовка к Фазе C.
        
        Returns:
            Список dict с ключами q, a или пустой список при ошибке.
        """
        if not article_plain_text or not self._client:
            return []
        text_snippet = (article_plain_text[:4000] + '...') if len(article_plain_text) > 4000 else article_plain_text
        prompt = (
            'На основе текста статьи ниже создай ровно 3 пары вопрос-ответ для блока FAQ. '
            'Ответ выведи только в формате JSON, без markdown и пояснений, массив объектов с ключами "q" и "a". '
            'Пример: [{"q": "Вопрос?", "a": "Ответ."}, ...]\n\nТекст статьи:\n' + text_snippet
        )
        try:
            raw = self._client.chat(message=prompt)
            if not raw or not raw.strip():
                return []
            s = raw.strip()
            s = re.sub(r'^```\w*\n?', '', s)
            s = re.sub(r'\n?```\s*$', '', s)
            data = json.loads(s)
            if not isinstance(data, list):
                return []
            result = []
            for item in data:
                if isinstance(item, dict) and 'q' in item and 'a' in item:
                    result.append({'q': str(item['q']).strip(), 'a': str(item['a']).strip()})
            return result[:5]
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка генерации FAQ: {e}")
            return []
    
    @staticmethod
    def _format_faq_html(faq_list: List[Dict]) -> str:
        """Формирует HTML-блок FAQ и LD+JSON FAQPage для вставки в контент статьи (ТЗ №4)."""
        if not faq_list:
            return ''
        parts = ['<div class="faq-block" style="margin-top:1.5rem;"><h3>Частые вопросы</h3>']
        for i, item in enumerate(faq_list, 1):
            q = item.get('q', '').replace('<', '&lt;').replace('>', '&gt;')
            a = item.get('a', '').replace('<', '&lt;').replace('>', '&gt;')
            parts.append(f'<p><strong>{i}. {q}</strong><br>{a}</p>')
        parts.append('</div>')
        questions_for_schema = [{'question': item.get('q', ''), 'answer': item.get('a', '')} for item in faq_list]
        try:
            from blog.schema import generate_faq_schema, schema_to_json
            faq_schema = generate_faq_schema(questions_for_schema)
            parts.append(f'<script type="application/ld+json">\n{schema_to_json(faq_schema)}\n</script>')
        except Exception as e:
            logger.debug("FAQ schema skip: %s", e)
        return '\n'.join(parts)
    
    def _check_quality_gate(self, content_result: Dict, image_result: Dict) -> tuple:
        """
        Quality Gate (ТЗ №4): проверка длины текста и наличия валидного изображения.
        Returns:
            (status, note): 'published' или 'draft', и примечание при сбое.
        """
        plain = (content_result.get('plain_text') or '').strip()
        min_len = MIN_TEXT_HOROSCOPE if getattr(self.template, 'category', None) == 'horoscope' else MIN_TEXT_PUBLISH
        if len(plain) < min_len:
            logger.warning(f"   ⚠️ Quality Gate: текст {len(plain)} символов (мин. {min_len})")
            return 'draft', QUALITY_GATE_NEEDS_EDIT
        has_image = bool(image_result.get('path'))
        if not has_image:
            logger.warning("   ⚠️ Quality Gate: нет изображения")
            return 'draft', QUALITY_GATE_NEEDS_EDIT
        return 'published', ''
    
    @staticmethod
    def _validate_image_exists(file_field) -> bool:
        """Проверка, что файл изображения физически существует на сервере (ТЗ №4)."""
        if not file_field or not getattr(file_field, 'name', None):
            return False
        try:
            from django.core.files.storage import default_storage
            return default_storage.exists(file_field.name)
        except Exception:
            return False
    
    def _generate_image(self, context: Dict) -> Dict:
        """
        Генерация изображения.
        
        Args:
            context: Контекст переменных
        
        Returns:
            Словарь с результатом (path, info, source_type)
        """
        logger.info("   🎨 Генерация изображения...")
        
        # Обновляем heartbeat
        if self._heartbeat:
            self._heartbeat.update()
        
        try:
            image_processor = ImageProcessor(self.template, self._client)
            image_path = image_processor.generate(context, title=context.get('title', ''))

            if not image_path:
                image_path = self._fallback_image_from_archive(context)

            logger.info(f"   ✅ Изображение обработано: {image_path or 'нет'}")

            return {
                'path': image_path,
                'info': None,
                'source_type': 'generated' if image_path else None,
            }

        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка генерации изображения: {e}")
            fallback = self._fallback_image_from_archive(context)
            return {'path': fallback, 'info': str(e), 'source_type': 'archive' if fallback else 'none'}

    def _fallback_image_from_archive(self, context: Dict):
        """
        Если GigaChat не смог нарисовать — берём последнюю картинку этого же знака зодиака.
        Образ знака живёт и эволюционирует: вчерашний кадр лучше пустоты.
        """
        try:
            zodiac_sign = context.get('zodiac_sign', '')
            category = getattr(self.template, 'blog_category', None)

            qs = Post._base_manager.filter(
                status='published',
                kartinka__isnull=False,
            ).exclude(kartinka='').order_by('-id')

            if zodiac_sign:
                candidate = qs.filter(title__icontains=zodiac_sign).first()
                if candidate and candidate.kartinka:
                    logger.info(f"   📦 Fallback: картинка от знака '{zodiac_sign}' (пост ID={candidate.id})")
                    return candidate.kartinka.name

            if category:
                candidate = qs.filter(category=category).first()
                if candidate and candidate.kartinka:
                    logger.info(f"   📦 Fallback: картинка из категории '{category}' (пост ID={candidate.id})")
                    return candidate.kartinka.name

            logger.warning("   ⚠️ Fallback: архив пуст, картинка не найдена")
            return None
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка fallback-поиска картинки: {e}")
            return None
    
    def _publish_post(self, content_result: Dict, image_result: Dict, context: Dict) -> Post:
        """
        Создание и публикация поста.
        
        Args:
            content_result: Результат генерации контента
            image_result: Результат генерации изображения
            context: Контекст переменных
        
        Returns:
            Созданный Post объект
        """
        logger.info("   📰 Создание поста...")
        
        # Определяем автора
        if self.template.default_author:
            author = self.template.default_author
        else:
            author = User.objects.filter(username='ai_assistant').first()
            author = author or User.objects.filter(is_superuser=True).first()
        
        # Категория
        category = self.template.blog_category or Category.objects.first()
        
        # Статус: по умолчанию published для AUTO
        want_published = self.config.mode == GeneratorMode.AUTO

        # ИИ не имеет права выпустить статью без картинки.
        # Если fallback тоже не нашёл — отменяем публикацию полностью.
        if want_published and not image_result.get('path'):
            logger.error("   🚫 AI Quality Gate: нет изображения после всех попыток. Пост НЕ создаётся.")
            raise ValueError("no_image_after_fallback")

        status, quality_note = self._check_quality_gate(content_result, image_result)
        if want_published and status == 'draft':
            logger.warning(f"   📋 Quality Gate: статья в черновик. {quality_note}")
        
        # Создаём пост (без общего atomic — иначе side-effects ломают транзакцию)
        if True:  # HOTFIX: disable atomic wrapper
            post = Post(
                title=content_result['title'],
                content=content_result['content'],
                category=category,
                author=author,
                description=strip_tags(content_result['content'])[:200],
                status=status,
            )
            if quality_note:
                post.ai_moderation_notes = quality_note
            post._skip_auto_moderation = True
            post._skip_auto_publication = True
            post.save()
            
            logger.info(f"   ✅ Пост создан: ID={post.id}, статус={status}")
            
            # Изображение + проверка существования файла (ТЗ №4)
            if image_result.get('path'):
                post.kartinka = image_result['path']
                post.save(update_fields=['kartinka'])
                if self._validate_image_exists(post.kartinka):
                    logger.info(f"   🖼️ Изображение добавлено: {image_result['path']}")
                else:
                    logger.warning("   ⚠️ Файл изображения не найден на диске")
                    if status == 'published':
                        post.status = 'draft'
                        post.ai_moderation_notes = (post.ai_moderation_notes or '') + ' Изображение отсутствует.'
                        post.save(update_fields=['status', 'ai_moderation_notes'])
                        status = 'draft'
            
            # Теги (через TagProcessor из Test_Promot)
            tag_processor = TagProcessor(self.template)
            valid_tags = tag_processor.generate(context)
            if valid_tags:
                post.tags.add(*valid_tags)
                logger.info(f"   🏷️ Теги добавлены: {len(valid_tags)} шт.")
        
        # Telegram временно отключен из критического пути (HOTFIX non-blocking)
        if self.config.mode == GeneratorMode.AUTO and status == 'published':
            logger.info("   ⏭️ Telegram отправка пропущена (HOTFIX non-blocking)")
        
        # Мгновенная индексация (ТЗ №4): Яндекс.Вебмастер / Google / IndexNow
        if status == 'published':
            self._submit_for_indexing(post)
        
        return post
    
    def _submit_for_indexing(self, post: Post):
        """Отправка статьи на индексацию сразу после публикации (ТЗ №4)."""
        try:
            from Asistent.schedule.services import submit_post_for_indexing
            result = submit_post_for_indexing(post.id)
            if result:
                logger.info(f"   📤 Индексация: {result}")
            else:
                logger.debug("   Индексация не выполнена (пост не published или ошибка)")
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка отправки на индексацию: {e}")
    
    def _send_to_telegram(self, post: Post):
        """
        Отправка в Telegram.
        
        Args:
            post: Post объект
        """
        try:
            from blog.telegram_utils import send_telegram_message
            post.refresh_from_db()
            success = send_telegram_message(post)
            
            if success:
                logger.info(f"   ✅ Отправлено в Telegram")
            else:
                logger.warning(f"   ⚠️ Не удалось отправить в Telegram")
        
        except Exception as e:
            logger.error(f"   ❌ Ошибка отправки в Telegram: {e}")
    
    def _save_to_session(
        self,
        content_result: Dict,
        image_result: Dict,
        context: Dict
    ) -> GenerationResult:
        """
        Сохранение результата в сессию (для INTERACTIVE режима).
        
        Args:
            content_result: Результат генерации контента
            image_result: Результат генерации изображения
            context: Контекст переменных
        
        Returns:
            GenerationResult с данными для сессии
        """
        logger.info("   💾 Сохранение в сессию (preview режим)")
        
        session_data = {
            'template_id': self.template.id,
            'title': content_result['title'],
            'content_html': content_result['content'],
            'plain_text': content_result['plain_text'],
            'image_path': image_result.get('path'),
            'image_source_type': image_result.get('source_type'),
            'context': context,
            'source_info': content_result.get('source_info'),  # Информация об источнике
            'prompt': content_result.get('prompt', ''),  # Промпт для генерации
            'parsed_content': content_result.get('parsed_content'),  # Спарсенный контент
        }
        
        return GenerationResult(
            success=True,
            title=content_result['title'],
            content=content_result['content'],
            image_path=image_result.get('path'),
            session_data=session_data,
            metrics=self._metrics.get_data() if self._metrics else {}
        )
    
    def _cleanup(self):
        """Очистка ресурсов"""
        logger.debug("   🧹 Очистка ресурсов")
        
        if self._queue_manager and self.schedule_id:
            self._queue_manager.remove_from_queue(self.schedule_id)
        
        if self._heartbeat:
            self._heartbeat.stop()


