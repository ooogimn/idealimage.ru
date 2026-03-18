"""
Упрощенные сервисы для генерации контента
БЕЗ автоматического определения модели - всегда GigaChat для текста

ТЗ №3 (Фаза B): валидация длины спаршенного текста (min 300 символов),
очистка от HTML/мусора перед отправкой в GigaChat, fallback на следующий источник.
"""
import re
import logging
from typing import Dict, List, Optional, Tuple
from django.utils.html import strip_tags
from Asistent.models import PromptTemplate
from Asistent.gigachat_api import get_gigachat_client, RateLimitCooldown
from Asistent.Test_Promot.test_prompt import render_template_text, GIGACHAT_TIMEOUT_ARTICLE, GIGACHAT_TIMEOUT_TITLE

logger = logging.getLogger(__name__)

# Минимум символов спаршенного текста для рерайта (иначе следующий URL или полная генерация)
MIN_PARSED_LENGTH = 300
# Максимум символов спаршенного текста в промпте (экономия токенов)
MAX_PARSED_TEXT_FOR_PROMPT = 8000


# ============================================================================
# СТРАТЕГИИ ГЕНЕРАЦИИ КОНТЕНТА
# ============================================================================

class ContentGenerationStrategy:
    """Базовый класс для стратегий генерации контента"""
    def generate(self, prompt: str, context: Dict) -> Tuple[str, Optional[str]]:
        raise NotImplementedError


class FullGenerationStrategy(ContentGenerationStrategy):
    """Полная генерация контента через AI"""
    
    def __init__(self, gigachat_client, timeout_seconds: int):
        self.client = gigachat_client
        self.timeout = timeout_seconds
    
    def generate(self, prompt: str, context: Dict) -> Tuple[str, Optional[str]]:
        """Генерация контента через GigaChat (всегда GigaChat для текста)"""
        logger.info("   Режим: ПОЛНАЯ ГЕНЕРАЦИЯ AI")
        system_prompt = context.get('_system_prompt') if context else None
        try:
            content = self.client.chat(message=prompt, system_prompt=system_prompt)
            return content, None
        except Exception as e:
            logger.error(f"   ❌ Ошибка генерации: {e}")
            raise


class ParseAndRewriteStrategy(ContentGenerationStrategy):
    """Парсинг источников и переписывание контента"""
    
    def __init__(self, urls: List[str], gigachat_client, timeout_seconds: int):
        self.urls = urls
        self.client = gigachat_client
        self.timeout = timeout_seconds
    
    def generate(self, prompt: str, context: Dict) -> Tuple[str, Optional[str], Optional[Dict]]:
        """Парсинг и переписывание контента (использует GigaChat для текста)"""
        from Asistent.parsers.universal_parser import UniversalParser
        
        logger.info("   Режим: ПАРСИНГ контента (первый успешный источник)")
        
        # Парсим первый успешный источник
        parsed_article = self._parse_first_successful_url()
        
        system_prompt = context.get('_system_prompt') if context else None
        if not parsed_article:
            logger.warning("   Парсинг не удался, fallback на прямую генерацию")
            return self.client.chat(message=prompt, system_prompt=system_prompt), None, None
        
        # Переписываем спаршенный контент (используем GigaChat для текста)
        rewrite_prompt = self._build_rewrite_prompt(prompt, parsed_article)
        content = self.client.chat(message=rewrite_prompt, system_prompt=system_prompt)
        
        source_info = f"Источник: {parsed_article['title']} ({parsed_article['url']})"
        return content, source_info, parsed_article
    
    def _parse_first_successful_url(self) -> Optional[Dict]:
        """Парсинг первого успешного URL. Если текст короче MIN_PARSED_LENGTH — пробуем следующий источник."""
        from Asistent.parsers.universal_parser import UniversalParser
        
        parser = UniversalParser()
        logger.info(f"   Попытка парсинга {len(self.urls)} источников (мин. {MIN_PARSED_LENGTH} символов)...")
        
        for url in self.urls:
            try:
                result = parser.parse_article(url, download_images=False)
                raw_text = (result.get('text') or '').strip()
                text_content = ParseAndRewriteStrategy._clean_parsed_text(raw_text)
                
                if not result.get('success') or not text_content:
                    continue
                if len(text_content) < MIN_PARSED_LENGTH:
                    logger.warning(f"   Текст с {url} слишком короткий ({len(text_content)} символов), пробуем следующий источник")
                    continue
                
                parsed = {
                    'title': (result.get('title', '') or '').strip() or 'Без названия',
                    'text': text_content[:MAX_PARSED_TEXT_FOR_PROMPT],
                    'url': url,
                }
                logger.info(f"   Спаршен источник: {parsed['title']} ({url}), {len(parsed['text'])} символов")
                return parsed
            
            except Exception as e:
                logger.error(f"   Ошибка парсинга {url}: {e}")
                continue
        
        return None
    
    @staticmethod
    def _clean_parsed_text(text: str) -> str:
        """Очистка спаршенного текста: HTML, лишние пробелы, переносы (экономия токенов, без ИИ)."""
        if not text or not isinstance(text, str):
            return ''
        s = strip_tags(text)
        s = re.sub(r'\s+', ' ', s)
        s = re.sub(r'\n\s*\n', '\n\n', s)
        return s.strip()
    
    @staticmethod
    def _build_rewrite_prompt(base_prompt: str, parsed: Dict) -> str:
        """Построение промпта для переписывания (текст уже очищен и обрезан)."""
        return (
            f"{base_prompt}\n\n"
            f"СПАРШЕННЫЙ КОНТЕНТ:\n"
            f"{parsed['title']}\n{parsed['text']}\n\n"
            f"ПЕРЕПИШИ КОНТЕНТ, сохраняя ключевые факты и структуру."
        )


class ContentGenerationFactory:
    """Фабрика стратегий генерации контента"""
    
    @staticmethod
    def create_strategy(
        template: PromptTemplate,
        gigachat_client,
        timeout_seconds: int,
        context: Optional[Dict] = None
    ) -> ContentGenerationStrategy:
        """
        Создает стратегию генерации на основе шаблона.
        
        Если есть URLs для парсинга - использует ParseAndRewriteStrategy (GigaChat-Max для парсинга)
        Иначе - FullGenerationStrategy (GigaChat для текста)
        
        Для гороскопов автоматически формирует URL для horo.mail.ru
        """
        content_type = template.content_source_type or 'generate'
        urls = []
        
        # Автоматическое формирование URL для гороскопов
        if template.category == 'horoscope' and context:
            horoscope_url = ContentGenerationFactory._build_horoscope_url(context)
            if horoscope_url:
                urls.append(horoscope_url)
                logger.info(f"   🔮 Автоматически добавлен URL гороскопа: {horoscope_url}")
                # Для гороскопов автоматически включаем парсинг
                content_type = 'parse'
        
        # Добавляем URL из шаблона (если есть)
        if content_type == 'parse' and template.content_source_urls:
            template_urls = [u.strip() for u in template.content_source_urls.splitlines() if u.strip()]
            urls.extend(template_urls)
        
        if urls:
            logger.info(f"   Используется стратегия: ПАРСИНГ ({len(urls)} источников)")
            return ParseAndRewriteStrategy(urls, gigachat_client, timeout_seconds)
        
        logger.info(f"   Используется стратегия: ПОЛНАЯ ГЕНЕРАЦИЯ AI")
        return FullGenerationStrategy(gigachat_client, timeout_seconds)
    
    @staticmethod
    def _build_horoscope_url(context: Dict) -> Optional[str]:
        """
        Формирует URL для парсинга гороскопа с horo.mail.ru
        
        Args:
            context: Контекст с переменными (zodiac_sign, date, next_date)
        
        Returns:
            URL для парсинга или None
        """
        zodiac_sign = context.get('zodiac_sign') or context.get('zodiac', '')
        if not zodiac_sign:
            return None
        
        # Маппинг русских названий знаков зодиака на английские для URL
        ZODIAC_SLUGS = {
            'овен': 'aries', 'телец': 'taurus', 'близнецы': 'gemini', 'рак': 'cancer',
            'лев': 'leo', 'дева': 'virgo', 'весы': 'libra', 'скорпион': 'scorpio',
            'стрелец': 'sagittarius', 'козерог': 'capricorn', 'водолей': 'aquarius', 'рыбы': 'pisces'
        }
        
        zodiac_lower = zodiac_sign.lower().strip()
        zodiac_en = ZODIAC_SLUGS.get(zodiac_lower)
        
        if not zodiac_en:
            logger.warning(f"   ⚠️ Неизвестный знак зодиака для URL: {zodiac_sign}")
            return None
        
        # Определяем дату (tomorrow по умолчанию для гороскопов)
        date_slug = 'tomorrow'
        # Можно добавить логику для 'today', если нужно
        
        # Формируем URL: https://horo.mail.ru/prediction/{zodiac}/{date}/
        url = f"https://horo.mail.ru/prediction/{zodiac_en}/{date_slug}/"
        
        return url


# ============================================================================
# СЕРВИС ГЕНЕРАЦИИ ЗАГОЛОВКОВ
# ============================================================================

class TitleGenerator:
    """Сервис для генерации заголовков статей"""
    
    def __init__(self, template: PromptTemplate, gigachat_client, timeout_seconds: int):
        self.template = template
        self.client = gigachat_client
        self.timeout = timeout_seconds
    
    def generate(self, context: Dict, article_text: str, provided_title: Optional[str] = None) -> str:
        """
        Генерация заголовка статьи.
        
        Args:
            context: Контекст переменных
            article_text: Текст статьи
            provided_title: Заголовок из формы (если есть)
        
        Returns:
            Сгенерированный заголовок
        """
        # 1. Приоритет: заголовок из формы
        if provided_title and provided_title.strip():
            logger.info("   Используется заголовок из формы")
            return provided_title.strip()
        
        # 2. Для гороскопов - БЕЗ AI, сразу автогенерация
        if self.template.category == 'horoscope':
            title = self._generate_horoscope_title(context)
            if title:
                return title
        
        # 3. Генерация через AI (если есть критерии) - только для НЕ гороскопов
        if self.template.title_criteria:
            title = self._generate_with_ai(context, article_text)
            if title:
                return title
        
        # 4. Fallback: первая строка статьи
        return self._extract_from_article(article_text)
    
    def _generate_with_ai(self, context: Dict, article_text: str) -> Optional[str]:
        """Генерация заголовка через AI (всегда GigaChat для текста)"""
        try:
            title_prompt = render_template_text(
                self.template.title_criteria,
                {**context, 'article_text': article_text}
            ).strip()
            
            if not title_prompt:
                return None
            
            title_response = self.client.chat(message=title_prompt)
            
            generated_title = strip_tags(title_response).strip()
            if generated_title:
                title = generated_title.splitlines()[0].strip()
                logger.info(f"   Заголовок сгенерирован AI: {title[:50]}...")
                return title
        
        except Exception as e:
            logger.error(f"   Ошибка генерации заголовка: {e}")
        
        return None
    
    @staticmethod
    def _generate_horoscope_title(context: Dict) -> Optional[str]:
        """Автогенерация заголовка для гороскопа"""
        zodiac_sign = context.get('zodiac_sign', '').strip()
        if not zodiac_sign:
            return None
        
        target_date = context.get('next_date') or context.get('date', '')
        weekday = context.get('weekday', '')
        season = context.get('season', '')
        
        # Формат: "{zodiac_sign} гороскоп на {date}, {weekday}, {season}"
        parts = [target_date, weekday, season]
        parts = [p for p in parts if p]  # Убираем пустые
        
        if parts:
            date_phrase = ", ".join(parts)
            title = f"{zodiac_sign} гороскоп на {date_phrase}"
        else:
            title = f"{zodiac_sign} гороскоп"
        
        logger.info(f"   Заголовок для гороскопа: {title}")
        return title
    
    def _extract_from_article(self, article_text: str) -> str:
        """Извлечение заголовка из первой строки статьи"""
        plain_text = strip_tags(article_text).strip()
        
        if not plain_text:
            return self.template.name or 'Новая статья'
        
        first_line = plain_text.splitlines()[0]
        title_candidate = first_line[:100]
        
        if len(first_line) > 100:
            title_candidate = title_candidate.rsplit(' ', 1)[0].strip() or title_candidate.strip()
        
        title = title_candidate or (self.template.name or 'Новая статья')
        logger.info(f"   Заголовок из статьи: {title[:50]}...")
        return title


# ============================================================================
# СЕРВИС ОБРАБОТКИ ИЗОБРАЖЕНИЙ
# ============================================================================

class ImageProcessor:
    """Сервис для обработки и генерации изображений"""
    
    def __init__(self, template: PromptTemplate, gigachat_client):
        self.template = template
        self.client = gigachat_client
    
    def generate(self, context: Dict, title: str) -> Optional[str]:
        """
        Генерация изображения через GigaChat.
        Единственный источник промпта — template.image_generation_criteria.
        """
        image_type = self.template.image_source_type or 'generate_auto'

        if image_type == 'none':
            return None

        criteria = (self.template.image_generation_criteria or '').strip()
        if criteria:
            # SafeFormatter: отсутствующие переменные заполняются пустой строкой
            class _SafeDict(dict):
                def __missing__(self, key):
                    return ''

            image_prompt = criteria.format_map(_SafeDict(context))
        else:
            # Fallback если критерии не заданы — минимальный промпт из заголовка
            image_prompt = title[:120] if title else context.get('zodiac_sign', 'гороскоп')
        
        try:
            import asyncio

            def _run_prompt(prompt_text: str) -> Optional[str]:
                # Правильная обработка event loop для Celery/Django окружения
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            return loop.run_until_complete(
                                self.client.generate_and_save_image(prompt=prompt_text)
                            )
                        finally:
                            loop.close()
                    return loop.run_until_complete(
                        self.client.generate_and_save_image(prompt=prompt_text)
                    )
                except RuntimeError:
                    return asyncio.run(
                        self.client.generate_and_save_image(prompt=prompt_text)
                    )

            filepath = _run_prompt(image_prompt)
            return filepath
        except Exception as e:
            logger.error(f"   ❌ Ошибка генерации изображения: {e}", exc_info=True)
            return None


# ============================================================================
# СЕРВИС ОБРАБОТКИ ТЕГОВ
# ============================================================================

class TagProcessor:
    """Сервис для обработки и генерации тегов"""
    
    def __init__(self, template: PromptTemplate):
        self.template = template
    
    def generate(self, context: Dict) -> List[str]:
        """
        Генерация списка тегов на основе критериев шаблона.
        
        Args:
            context: Контекст переменных
        
        Returns:
            Список валидных тегов
        """
        if not self.template.tags_criteria:
            return []
        
        tags_list = []
        
        for tag_item in self.template.tags_criteria.split(','):
            tag_item = tag_item.strip()
            
            if not tag_item:
                continue
            
            # В кавычках - буквальное значение
            if tag_item.startswith('"') and tag_item.endswith('"'):
                tags_list.append(tag_item[1:-1])
            # Переменная из контекста
            elif tag_item.startswith('{') and tag_item.endswith('}'):
                var_name = tag_item[1:-1]
                value = context.get(var_name, '')
                if value:
                    tags_list.append(str(value))
            # Обычный текст
            else:
                tags_list.append(tag_item)
        
        return tags_list


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ
# ============================================================================

class ContextBuilder:
    """Построитель контекста переменных"""
    
    def __init__(self, template: PromptTemplate, user_variables: Dict, mode: str = 'auto'):
        self.template = template
        self.user_variables = user_variables
        self.mode = mode
    
    def build(self) -> Dict:
        """Построение полного контекста переменных"""
        context = self.user_variables.copy()
        
        # Добавляем переменные из шаблона
        if self.template.variables:
            for var_name in self.template.variables:
                if var_name not in context:
                    context[var_name] = ""
        
        return context


class ScheduleNotificationService:
    """Сервис для отправки уведомлений о расписаниях"""
    
    @staticmethod
    def send_notification(schedule, created_posts, success=True, error=None):
        """Отправка уведомления о выполнении расписания"""
        # Упрощенная версия - логирование
        if success:
            logger.info(f"✅ Расписание {schedule.name} выполнено успешно: {len(created_posts or [])} статей")
        else:
            logger.error(f"❌ Расписание {schedule.name} завершилось с ошибкой: {error}")


class ScheduleMetadataService:
    """Сервис для работы с метаданными расписаний"""
    pass


class ScheduleTimestampService:
    """Сервис для работы с временными метками расписаний"""
    pass

