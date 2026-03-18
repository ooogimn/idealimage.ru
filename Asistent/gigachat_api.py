"""
Интеграция с GigaChat API
Использует официальный SDK от Сбера.
Авторизация: в личном кабинете Sber Studio выдают Base64(Client_ID:Client_Secret).
В .env можно задать либо готовый ключ (GIGACHAT_API_KEY), либо пару Client_ID + GIGACHAT_API_KEY (как секрет) — тогда ключ соберётся автоматически.
"""
import base64
import os
import json
import logging
import time
import uuid
import asyncio
import errno
from decimal import Decimal
from typing import Dict, List, Optional
from functools import wraps
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from .prompt_registry import PromptRegistry
from Asistent.services.integration_monitor import record_integration_error
from .models import GigaChatUsageStats

logger = logging.getLogger(__name__)


# ============================================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С БАЛАНСОМ GIGACHAT
# ============================================================================



# ============================================================================
# УМНОЕ РАСПРЕДЕЛЕНИЕ ЗАДАЧ ПО МОДЕЛЯМ GIGACHAT
# ============================================================================

# Оптимальные модели для разных типов задач (по рекомендациям пользователя)
TASK_TO_MODEL = {
    # GigaChat Lite (194₽/1M) - простые рутинные задачи
    'seo_metadata': 'GigaChat',           # SEO мета-теги
    'faq_generation': 'GigaChat',         # FAQ блоки
    'alt_tags': 'GigaChat',               # Alt-теги изображений
    'comment_moderation': 'GigaChat',     # Модерация комментариев
    'summarize': 'GigaChat',              # Сводки источников
    'simple_commands': 'GigaChat',        # Простые команды AI-агента
    
    # GigaChat Pro (1500₽/1M) - средней сложности задачи
    'article_moderation': 'GigaChat',     # Модерация статей авторов
    'draft_improvement': 'GigaChat',      # Улучшение черновиков
    'chatbot': 'GigaChat-Pro',            # Чат-бот для пользователей (GigaChat-Max отключен)
    'style_analysis': 'GigaChat-Pro',     # Анализ стиля автора
    'schedule_management': 'GigaChat-Pro',# Управление расписаниями
    
    # GigaChat Max (1950₽/1M) - сложные креативные задачи
    'article_update': 'GigaChat-Pro',     # Обновление старых статей
    'creative': 'GigaChat-Pro',           # Креативные задачи (GigaChat-Max отключен)
    'image_generation': 'GigaChat',       # Генерация изображений (эконом-режим по умолчанию)
    
    # Генерация статей — теперь на GigaChat (Lite), так как это массовая рутина
    'article_single': 'GigaChat',          # ✅ Обычные статьи
    'article_series': 'GigaChat',          # ✅ Серии статей / подборки
    'horoscope': 'GigaChat',               # ✅ Гороскопы (текст) - используем Лайт для экономии
    'faq': 'GigaChat',                     # Генерация FAQ блоков
    'comments': 'GigaChat',                # Комментарии и ответы
    
    # По умолчанию - Pro (баланс качества и цены)
    'general': 'GigaChat-Pro',
}

# Fallback цепочки при нехватке токенов на оптимальной модели
# GigaChat-Max отключен - не используется
FALLBACK_CHAINS = {
    'GigaChat-Max': ['GigaChat-Pro', 'GigaChat'],                      # Max отключен → Pro → Lite
    'GigaChat-Pro': ['GigaChat-Pro', 'GigaChat'],                      # Pro → Lite (БЕЗ Max)
    'GigaChat': ['GigaChat', 'GigaChat-Pro'],                          # Lite → Pro (БЕЗ Max)
}

STRICT_TASK_TYPES = {
    'creative',
    'image_generation',
    'article_update',
    'style_analysis',
}

# Настройки rate limit для генерации изображений
IMAGE_RATE_LIMIT_LOCK_KEY = "gigachat:image_generation:lock"
IMAGE_RATE_LIMIT_COOLDOWN_KEY = "gigachat:image_generation:cooldown"
IMAGE_RATE_LIMIT_LOCK_TTL = getattr(settings, 'GIGACHAT_IMAGE_LOCK_TTL', 75)
IMAGE_RATE_LIMIT_MAX_WAIT = getattr(settings, 'GIGACHAT_IMAGE_LOCK_MAX_WAIT', 90)
IMAGE_RATE_LIMIT_COOLDOWN = getattr(settings, 'GIGACHAT_IMAGE_COOLDOWN_SECONDS', 90)


class RateLimitCooldown(Exception):
    """Исключение для ситуаций, когда требуется подождать перед повторным запросом"""

    def __init__(self, retry_after: int, reason: str = ""):
        self.retry_after = max(int(retry_after), 1)
        self.reason = reason
        message = f"Достигнут лимит GigaChat. Повторите через {self.retry_after} сек."
        if reason:
            message += f" Причина: {reason}"
        super().__init__(message)


"""
Декоратор для автоматических повторных попыток при ошибке 429 (Rate Limit)
Args: max_retries: Максимальное количество попыток (по умолчанию 3)
      base_delay: Базовая задержка в секундах (по умолчанию 5)   
Использует экспоненциальную задержку: 5s, 10s, 20s
"""
def rate_limit_retry(max_retries=3, base_delay=5):
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e)
                    error_repr = repr(e)
                    
                    # Проверяем является ли это ошибкой Rate Limit
                    is_rate_limit = (
                        '429' in error_str or 
                        '429' in error_repr or
                        'Too Many Requests' in error_str or
                        'Too Many Requests' in error_repr or
                        'rate limit' in error_str.lower() or
                        'rate limit' in error_repr.lower()
                    )
                    
                    if is_rate_limit and attempt < max_retries - 1:
                        # Экспоненциальная задержка: 5s → 10s → 20s
                        wait_time = base_delay * (2 ** attempt)
                        logger.warning(f"⚠️ Rate Limit (429) в {func.__name__}!")
                        logger.warning(f"   Повторная попытка {attempt + 2}/{max_retries} через {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    
                    # Если это не Rate Limit или попытки закончились - пробрасываем ошибку
                    raise
                    
            # Если все попытки исчерпаны
            logger.error(f"❌ Все {max_retries} попытки исчерпаны для {func.__name__}")
            return None
            
        return wrapper
    return decorator


def _normalize_gigachat_credentials():
    """
    Возвращает credentials для GigaChat SDK: Base64(Client_ID:Client_Secret).
    Вариант 1: в .env только GIGACHAT_API_KEY = готовая строка из кабинета Sber Studio (Ключ авторизации).
    Вариант 2: в .env заданы Client_ID и GIGACHAT_API_KEY (как Client Secret) — собираем Base64 здесь.
    """
    api_key = (getattr(settings, 'GIGACHAT_API_KEY', None) or os.getenv('GIGACHAT_API_KEY') or '').strip()
    client_id = (getattr(settings, 'Client_ID', None) or os.getenv('Client_ID') or '').strip()
    if client_id and api_key:
        # Явно задана пара — собираем Base64(Client_ID:Client_Secret)
        raw = f"{client_id}:{api_key}"
        creds = base64.b64encode(raw.encode('utf-8')).decode('ascii')
        logger.info("GigaChat: credentials собраны из Client_ID + GIGACHAT_API_KEY (Base64)")
        return creds
    if api_key and not client_id:
        logger.warning(
            "GigaChat: задан только GIGACHAT_API_KEY. Если это Client Secret — добавь в .env Client_ID=... (UUID из Sber Studio)"
        )
    return api_key


"""Клиент для работы с GigaChat API"""
class GigaChatClient:
    
    """Инициализация клиента"""
    def __init__(self):
        self._credentials = _normalize_gigachat_credentials()
        self.api_key = getattr(settings, 'GIGACHAT_API_KEY', os.getenv('GIGACHAT_API_KEY'))
        self.model = getattr(settings, 'GIGACHAT_MODEL', 'GigaChat')
        self.client = None
        self._initialize_client()
    
    """Инициализация SDK клиента"""
    def _initialize_client(self):
        try:
            from gigachat import GigaChat
            if not self._credentials:
                logger.error("GigaChat: не заданы credentials (GIGACHAT_API_KEY или пара Client_ID + GIGACHAT_API_KEY)")
                self.client = None
                return
            self.client = GigaChat(
                credentials=self._credentials,
                model=self.model,  # Указываем модель при создании клиента
                verify_ssl_certs=False,
                scope="GIGACHAT_API_PERS"
            )
            logger.info(f"GigaChat client initialized successfully with model: {self.model}")
        except ImportError:
            logger.error("GigaChat SDK not installed. Run: pip install gigachat")
            self.client = None
        except Exception as e:
            logger.error(f"Failed to initialize GigaChat client: {e}")
            self.client = None
    
    @rate_limit_retry(max_retries=3, base_delay=5)
    def chat(self, message: str, system_prompt: str = None) -> str:
        """
        Базовый метод chat.
        ВАЖНО: Для контроля токенов используйте GigaChatSmartClient!
        Этот метод НЕ регистрирует использование токенов.
        """
        if not self.client:
            raise Exception("GigaChat клиент не инициализирован. Проверьте GIGACHAT_API_KEY в настройках.")
        
        try:
            # Формируем полное сообщение
            full_message = message
            if system_prompt:
                full_message = f"{system_prompt}\n\n{message}"
            
            # Отправляем запрос через SDK (модель уже указана при инициализации клиента)
            logger.info(f"🤖 Запрос к GigaChat модель: {self.model}")
            response = self.client.chat(full_message)
            
            # Извлекаем текст ответа
            if hasattr(response, 'choices') and len(response.choices) > 0:
                return response.choices[0].message.content
            elif isinstance(response, str):
                # Если ответ - это просто строка
                return response
            else:
                logger.error(f"Неожиданный формат ответа от GigaChat: {response}")
                return "Ошибка: неожиданный формат ответа от GigaChat"
                
        except Exception as e:
            error_str = str(e)
            error_repr = repr(e)
            
            # Проверяем, является ли это ошибкой 429 (Rate Limit)
            is_rate_limit = (
                '429' in error_str or 
                '429' in error_repr or
                'Too Many Requests' in error_str or
                'Too Many Requests' in error_repr or
                'rate limit' in error_str.lower() or
                'rate limit' in error_repr.lower()
            )
            
            if is_rate_limit:
                # Преобразуем в специальное исключение для обработки в GigaChatSmartClient
                logger.warning(f"⚠️ Rate Limit (429) в базовом методе chat: {error_str[:100]}")
                raise RateLimitCooldown(
                    retry_after=120,  # 2 минуты по умолчанию для 429
                    reason="429 Too Many Requests от GigaChat API"
                )
            
            logger.error(f"Ошибка при обращении к GigaChat: {e}")
            raise Exception(f"Ошибка GigaChat API: {str(e)}")
    
    """Проверка подключения к API"""
    def check_connection(self) -> bool:
        if not self.client:
            return False
        
        try:
            response = self.chat("Привет")
            return bool(response)
        except Exception as e:
            logger.error(f"GigaChat connection check failed: {e}")
            return False
    
    
    
    """Получение баланса токенов для всех моделей"""
    def get_balance(self) -> Dict:
            
        if not self.client:
            logger.warning("GigaChat клиент не инициализирован")
            return {}
        
        try:
            response = self.client.get_balance()
            
            # Возвращает: {"balance": [{"usage": "GigaChat", "value": 50000}, ...]}
            balance_dict = {}
            
            # Парсим ответ API
            if hasattr(response, 'balance'):
                # Объектный формат (официальный SDK)
                for item in response.balance:
                    model_name = item.usage if hasattr(item, 'usage') else item.get('usage')
                    value = item.value if hasattr(item, 'value') else item.get('value')
                    
                    # Нормализуем названия моделей
                    if model_name and value is not None:
                        balance_dict[model_name] = float(value)
                        
            elif isinstance(response, dict):
                # Dict формат
                for item in response.get('balance', []):
                    model_name = item.get('usage')
                    value = item.get('value')
                    
                    if model_name and value is not None:
                        balance_dict[model_name] = float(value)
            
            # Маппинг API ключей на внутренние названия моделей
            # API возвращает "embeddings", а мы используем "GigaChat-Embeddings"
            if 'embeddings' in balance_dict and 'GigaChat-Embeddings' not in balance_dict:
                balance_dict['GigaChat-Embeddings'] = balance_dict['embeddings']
            
            # Добавляем модели с нулевым балансом если не вернулись из API
            # (важно для корректного отображения в Dashboard)
            for model in ['GigaChat', 'GigaChat-Pro', 'GigaChat-Max', 'GigaChat-Embeddings']:
                if model not in balance_dict:
                    balance_dict[model] = 0.0
            
            logger.info(f"Получен баланс GigaChat: {balance_dict}")
            return balance_dict
            
        except Exception as e:
            logger.error(f"Ошибка получения баланса GigaChat: {e}", exc_info=True)
            # Возвращаем пустой dict с нулевыми балансами
            return {
                'GigaChat': 0.0,
                'GigaChat-Pro': 0.0,
                'GigaChat-Max': 0.0,
                'GigaChat-Embeddings': 0.0,
            }
    
    """Модерация статьи по критериям"""
    def moderate_article(self, article_text: str, criteria_text: str) -> Dict:
        
        if not self.client:
            return {
                'verdict': 'error',
                'notes': 'GigaChat API не инициализирован'
            }
        
        prompt = PromptRegistry.render(
            'GIGACHAT_MODERATE_ARTICLE_PROMPT',
            params={
                'criteria': criteria_text,
                'article': article_text,
            },
            default=(
                "Ты профессиональный редактор контента.\n"
                "Проанализируй следующую статью на соответствие критериям.\n"
                "КРИТЕРИИ ПРОВЕРКИ: {criteria}\n"
                "ТЕКСТ СТАТЬИ: {article}\n"
                "ВАЖНО: Верни ответ СТРОГО в формате JSON:\n"
                "{{\n"
                "    \"verdict\": \"approve или reject\",\n"
                "    \"notes\": \"детальный список замечаний или подтверждение качества\",\n"
                "    \"score\": \"оценка от 1 до 10\"\n"
                "}}\n"
                "Анализируй объективно и конструктивно. Если статья соответствует критериям - одобряй,\n"
                "если нет - дай чёткие рекомендации по доработке."
            ),
        )

        try:
            # Используем метод chat с промптом
            result_text = self.chat(prompt)
            
            # Попытка распарсить JSON из ответа
            try:
                # Извлекаем JSON из текста (может быть обёрнут в markdown)
                if '```json' in result_text:
                    json_start = result_text.find('```json') + 7
                    json_end = result_text.find('```', json_start)
                    result_text = result_text[json_start:json_end].strip()
                elif '```' in result_text:
                    json_start = result_text.find('```') + 3
                    json_end = result_text.find('```', json_start)
                    result_text = result_text[json_start:json_end].strip()
                
                result = json.loads(result_text)
                
                # Валидация результата
                if 'verdict' not in result:
                    result['verdict'] = 'reject'
                if 'notes' not in result:
                    result['notes'] = result_text
                
                return result
                
            except json.JSONDecodeError:
                # Если не удалось распарсить JSON, возвращаем весь текст как замечание
                logger.warning(f"Failed to parse JSON from GigaChat response: {result_text}")
                return {
                    'verdict': 'reject' if any(word in result_text.lower() for word in ['отклон', 'reject', 'не соответств', 'ошибк']) else 'approve',
                    'notes': result_text,
                    'score': 5
                }
        
        except Exception as e:
            logger.error(f"Error during article moderation: {e}")
            return {
                'verdict': 'error',
                'notes': f'Ошибка при обращении к AI: {str(e)}'
            }
    
    """Генерация статьи на основе данных из источников"""
    @rate_limit_retry(max_retries=3, base_delay=5)
    def generate_article(
        self,
        topic: str,
        sources_summary: str,
        word_count: int,
        keywords: List[str],
        tone: str = "дружелюбный и экспертный",
        category: str = ""
        ) -> str:
        
        if not self.client:
            return "Ошибка: GigaChat API не инициализирован"
        
        keywords_text = ", ".join(keywords) if keywords else "отсутствуют"
        
        prompt = PromptRegistry.render(
            'GIGACHAT_GENERATE_ARTICLE_PROMPT',
            params={
                'topic': topic,
                'category': category,
                'word_count': word_count,
                'tone': tone,
                'sources_summary': sources_summary,
                'keywords': keywords_text,
            },
            default=(
                "Напишите уникальную статью для женского журнала \"Идеальный Образ\":\n"
                "🌟 Тема: {topic}\n"
                "📝 Категория: {category}\n"
                "📊 Объем: {word_count} слов\n"
                "🎯 Требования:\n"
                "- Тон: {tone}, живым и интересным языком\n"
                "- Уникальность: полностью переработанная статья, без прямого копирования исходников ({sources_summary})\n"
                "- Оформление: структура HTML для редактора CKEditor (заголовки h2/h3, списки ul/ol, акценты strong/em)\n"
                "- Ключевые слова: {keywords}\n"
                "- Советы и рекомендации приветствуются\n"
                "- Начинайте введение с интересного факта или риторического вопроса\n"
                "🛠️ Структура статьи:\n\n"
                "<h2>Введение</h2>\n"
                "<p>Привлекающее начало статьи.</p>\n\n"
                "<h2>Основная тема</h2>\n"
                "<h3>Первый важный аспект</h3>\n"
                "<p>Детали и важные моменты.</p>\n"
                "<ul>\n"
                "<li><strong>Ключевое положение 1:</strong> подробнее здесь</li>\n"
                "<li><strong>Ключевое положение 2:</strong> другая деталь</li>\n"
                "</ul>\n\n"
                "<h3>Практические рекомендации</h3>\n"
                "<ol>\n"
                "<li><strong>Шаг 1:</strong> первое действие</li>\n"
                "<li><strong>Шаг 2:</strong> второе действие</li>\n"
                "</ol>\n\n"
                "<h2>Заключение</h2>\n"
                "<p>Краткий итог статьи.</p>\n\n"
                "📑 Результат:\n"
                "HTML-код статьи с правильной разметкой и уникальной информацией."
            ),
        )

        try:
            # Используем метод chat с промптом
            article_text = self.chat(prompt)
            
            logger.info(f"Article generated successfully. Length: {len(article_text)} chars")
            return article_text
            
        except Exception as e:
            logger.error(f"Error during article generation: {e}")
            return f"Ошибка при генерации статьи: {str(e)}"
    
    """Создание сводки из нескольких источников"""
    @rate_limit_retry(max_retries=3, base_delay=5)
    def summarize_sources(self, sources_data: List[Dict]) -> str:
        
        if not self.client or not sources_data:
            return ""
        
        sources_text = "\n\n".join([
            f"Источник: {s.get('title', 'Без названия')}\n{s.get('content', '')[:1000]}"
            for s in sources_data[:5]  # Ограничиваем 5 источниками
        ])
        
        prompt = PromptRegistry.render(
            'GIGACHAT_SUMMARIZE_SOURCES_PROMPT',
            params={'sources': sources_text},
            default=(
                "Проанализируй следующие новости и создай краткую сводку ключевых моментов: {sources}\n"
                "Верни структурированную сводку, выделив:\n"
                "1. Основные темы и тренды\n"
                "2. Важные факты и цифры\n"
                "3. Интересные детали для статьи\n"
                "Сводка должна быть компактной (не более 500 слов)."
            ),
        )

        try:
            # Используем метод chat с промптом
            summary = self.chat(prompt)
            return summary
            
        except Exception as e:
            logger.error(f"Error during sources summarization: {e}")
            # Возвращаем просто объединённый текст
            return sources_text[:2000]
    
    """Улучшение текста по замечаниям"""
    def improve_text(self, text: str, improvements: str) -> str:
        if not self.client:
            return text
        
        prompt = PromptRegistry.render(
            'GIGACHAT_IMPROVE_TEXT_PROMPT',
            params={'text': text, 'improvements': improvements},
            default=(
                "Ты редактор. Улучши следующий текст, учитывая замечания.\n"
                "ИСХОДНЫЙ ТЕКСТ: {text}\n"
                "ЗАМЕЧАНИЯ: {improvements}\n"
                "Верни улучшенную версию текста, сохранив его общую структуру и смысл, но исправив указанные проблемы."
            ),
        )

        try:
            # Используем метод chat с промптом
            improved_text = self.chat(prompt)
            return improved_text
            
        except Exception as e:
            logger.error(f"Error during text improvement: {e}")
            return text
    
   
    """Генерация SEO-оптимизированных метаданных для статьи"""
    @rate_limit_retry(max_retries=3, base_delay=5)
    def generate_seo_metadata(
        self,
        title: str,
        content: str,
        keywords: List[str],
        category: str = "",
        use_cache: bool = True
        ) -> Dict:
        
        if not self.client:
            return self._generate_fallback_seo(title, content, keywords)
        
        # Кэширование удалено - всегда генерируем заново
        return self._generate_seo_internal(title, content, keywords, category)
    
    """Внутренний метод генерации SEO (без кэша)"""
    def _generate_seo_internal(self, title: str, content: str, keywords: List[str], category: str) -> Dict:
        # Обрезаем контент для промпта (первые 500 символов)
        import re
        clean_content = re.sub(r'<[^>]+>', ' ', content)  # Удаляем HTML теги
        clean_content = re.sub(r'\s+', ' ', clean_content).strip()
        content_preview = clean_content[:500]
        
        keywords_text = ", ".join(keywords) if keywords else "не указаны"
        
        prompt = PromptRegistry.render(
            'GIGACHAT_SEO_METADATA_PROMPT',
            params={
                'title': title,
                'category': category if category else 'не указана',
                'content_preview': content_preview,
                'keywords': keywords_text,
            },
            default=(
                "Ты SEO-эксперт. Создай оптимизированные метаданные для статьи женского журнала о красоте и моде.\n"
                "📰 ЗАГОЛОВОК СТАТЬИ: {title}\n"
                "📂 КАТЕГОРИЯ: {category}\n"
                "📝 НАЧАЛО СТАТЬИ: {content_preview}...\n"
                "🔑 КЛЮЧЕВЫЕ СЛОВА: {keywords}\n"
                "✅ ЗАДАНИЕ: Создай SEO-метаданные, которые:\n"
                "- Привлекут клики из поисковиков (Яндекс, Google)\n"
                "- Будут привлекательны в соцсетях\n"
                "- Содержат ключевые слова\n"
                "- Соответствуют содержанию статьи\n"
                "ВАЖНО: Верни ответ СТРОГО в формате JSON:\n"
                "{{\n"
                "    \"meta_title\": \"SEO заголовок до 60 символов с ключевыми словами\",\n"
                "    \"meta_description\": \"Привлекательное описание 150-160 символов, которое заставит кликнуть\",\n"
                "    \"og_title\": \"Заголовок для Facebook/VK до 95 символов\",\n"
                "    \"og_description\": \"Описание для соцсетей до 200 символов\",\n"
                "    \"focus_keyword\": \"главное ключевое слово из списка\"\n"
                "}}\n"
                "ТРЕБОВАНИЯ:\n"
                "- meta_title: Включи главное ключевое слово в начале\n"
                "- meta_description: Используй призыв к действию (\"Узнайте\", \"Откройте для себя\")\n"
                "- og_title: Более эмоциональный и привлекающий внимание\n"
                "- og_description: Тизер, который интригует\n"
                "- focus_keyword: Самое релевантное ключевое слово"
            ),
        )

        try:
            # Используем метод chat с промптом
            result_text = self.chat(prompt)
            
            # Извлекаем JSON из ответа
            try:
                if '```json' in result_text:
                    json_start = result_text.find('```json') + 7
                    json_end = result_text.find('```', json_start)
                    result_text = result_text[json_start:json_end].strip()
                elif '```' in result_text:
                    json_start = result_text.find('```') + 3
                    json_end = result_text.find('```', json_start)
                    result_text = result_text[json_start:json_end].strip()
                
                seo_data = json.loads(result_text)
                
                # Валидация и ограничение длин
                seo_data['meta_title'] = seo_data.get('meta_title', title)[:60]
                seo_data['meta_description'] = seo_data.get('meta_description', content_preview)[:160]
                seo_data['og_title'] = seo_data.get('og_title', title)[:95]
                seo_data['og_description'] = seo_data.get('og_description', content_preview)[:200]
                seo_data['focus_keyword'] = seo_data.get('focus_keyword', keywords[0] if keywords else '')[:100]
                
                logger.info(f"SEO metadata generated successfully")
                return seo_data
                
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from GigaChat SEO response")
                return self._generate_fallback_seo(title, content_preview, keywords)
        
        except Exception as e:
            logger.error(f"Error during SEO metadata generation: {e}")
            return self._generate_fallback_seo(title, content_preview, keywords)
    
    """Генерация статьи в стиле конкретного автора"""
    @rate_limit_retry(max_retries=3, base_delay=5)
    def generate_article_in_author_style(
        self,
        topic: str,
        sources_summary: str,
        word_count: int,
        keywords: List[str],
        tone: str,
        category: str,
        style_profile: Dict
        ) -> str:
        
        if not self.client:
            logger.error("❌ GigaChat client not initialized")
            return ""
        
        # Формируем промпт со стилистическими требованиями
        style_instructions = self._build_style_instructions(style_profile)
        
        prompt = PromptRegistry.render(
            'GIGACHAT_AUTHOR_STYLE_ARTICLE_PROMPT',
            params={
                'style_instructions': style_instructions,
                'topic': topic,
                'sources_summary': sources_summary,
                'word_count': word_count,
                'category': category,
                'tone': tone,
                'keywords': ', '.join(keywords) if keywords else 'нет',
            },
            default=(
                "Ты - профессиональный копирайтер, пишущий статьи для сайта о моде и красоте.\n"
                "📊 АНАЛИЗ СТИЛЯ АВТОРА: {style_instructions}\n"
                "🎯 ЗАДАЧА: Напиши статью на тему: \"{topic}\"\n"
                "📝 ИСТОЧНИКИ: {sources_summary}\n"
                "✅ ТРЕБОВАНИЯ:\n"
                "• Объём: {word_count} слов (строго!)\n"
                "• Категория: {category}\n"
                "• Тон: {tone}\n"
                "• Ключевые фразы для включения: {keywords}\n"
                "• ВАЖНО: Пиши ТОЧНО в стиле автора, используя его характерные фразы и приёмы!\n"
                "📐 СТРУКТУРА HTML (строго соблюдай):\n"
                "🎨 СТИЛЬ:\n"
                "• Имитируй голос автора (см. анализ выше)\n"
                "✨ УНИКАЛЬНОСТЬ:\n"
                "• Создай оригинальный контент на основе источников\n"
                "Верни ТОЛЬКО HTML код без markdown обёрток и комментариев!"
            ),
        )

        try:
            # Используем метод chat с промптом
            article_text = self.chat(prompt)
            
            # Очистка от markdown обёрток
            article_text = article_text.replace('```html', '').replace('```', '').strip()
            
            logger.info(f"✅ Статья в стиле автора сгенерирована ({len(article_text)} символов)")
            return article_text
            
        except Exception as e:
            logger.error(f"❌ Ошибка генерации в стиле автора: {e}")
            return ""
    
    """Формирует инструкции по стилю на основе анализа"""
    def _build_style_instructions(self, style_profile: Dict) -> str:
        instructions = []
        
        # Характерные фразы автора
        if 'top_phrases' in style_profile and style_profile['top_phrases']:
            phrases = [item['item'] for item in style_profile['top_phrases'][:5]]
            instructions.append(f"Используй эти характерные фразы: {', '.join(phrases)}")
        
        # Структура предложений
        if 'avg_sentence_length' in style_profile:
            instructions.append(f"Средняя длина предложения: {style_profile['avg_sentence_length']:.0f} слов")
        
        # Структура абзацев
        if 'avg_paragraph_length' in style_profile:
            instructions.append(f"Средняя длина абзаца: {style_profile['avg_paragraph_length']:.0f} слов")
        
        # Тип заголовков
        if 'heading_types' in style_profile:
            instructions.append(f"Стиль заголовков: {', '.join(style_profile['heading_types'])}")
        
        # Use of emojis
        if 'emoji_usage' in style_profile:
            emoji_level = 'часто' if style_profile['emoji_usage'] > 5 else ('умеренно' if style_profile['emoji_usage'] > 2 else 'редко')
            instructions.append(f"Использование эмодзи: {emoji_level}")
        
        # Голос автора
        if 'writing_voice' in style_profile:
            instructions.append(f"Голос: {style_profile['writing_voice']}")
        
        # Примеры отрывков
        if 'best_excerpts' in style_profile and style_profile['best_excerpts']:
            instructions.append("\nПРИМЕРЫ ЛУЧШИХ ОТРЫВКОВ АВТОРА:")
            for i, excerpt in enumerate(style_profile['best_excerpts'][:2], 1):
                instructions.append(f"{i}. \"{excerpt}\"")
        
        return '\n'.join(instructions)
    
    """Фолбэк генерация SEO метаданных без AI"""
    def _generate_fallback_seo(self, title: str, content: str, keywords: List[str]) -> Dict:
        import re
        
        # Очищаем контент от HTML
        clean_content = re.sub(r'<[^>]+>', ' ', content)
        clean_content = re.sub(r'\s+', ' ', clean_content).strip()
        
        # Базовые метаданные
        meta_title = title[:57] + '...' if len(title) > 60 else title
        meta_description = clean_content[:157] + '...' if len(clean_content) > 160 else clean_content
        
        return {
            'meta_title': meta_title,
            'meta_description': meta_description,
            'og_title': title[:92] + '...' if len(title) > 95 else title,
            'og_description': clean_content[:197] + '...' if len(clean_content) > 200 else clean_content,
            'focus_keyword': keywords[0] if keywords else ''
        }
    
    """Генерация изображения через GigaChat"""
    @rate_limit_retry(max_retries=3, base_delay=5)
    def generate_image(self, prompt: str, width: int = 1024, height: int = 1024) -> Optional[str]:
        
        if not self.client:
            raise Exception("GigaChat клиент не инициализирован")
        
        try:
            logger.info(f"🎨 Генерация изображения через GigaChat...")
            logger.info(f"   Промпт: {prompt[:100]}...")
            
            # В GigaChat SDK 0.1.42+ используем Chat API с моделью GigaChat-Img
            # Формируем запрос для генерации изображения
            messages = [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            
            # Вызываем Chat API с моделью для генерации изображений
            response = self.client.chat(
                model="GigaChat-Img",  # Модель для генерации изображений
                messages=messages,
                function_call="auto"
            )
            
            # Проверяем наличие изображения в ответе
            if response and hasattr(response, 'choices') and len(response.choices) > 0:
                choice = response.choices[0]
                message = choice.message
                
                # В SDK 0.1.42 изображение может быть в attachments
                if hasattr(message, 'attachments') and message.attachments:
                    for attachment in message.attachments:
                        if attachment.type == 'image':
                            # Получаем base64 данные
                            image_data = attachment.content
                            logger.info(f"   ✅ GigaChat сгенерировал изображение (base64)")
                            logger.info(f"   📦 Размер: {len(image_data)} символов base64")
                            return image_data
                
                # Альтернативный формат: изображение в content
                if hasattr(message, 'content') and 'data:image' in str(message.content):
                    content = str(message.content)
                    # Извлекаем base64 из data:image/png;base64,<данные>
                    if 'base64,' in content:
                        image_data = content.split('base64,')[1]
                        logger.info(f"   ✅ GigaChat сгенерировал изображение (base64 из content)")
                        return image_data
            
            logger.warning(f"   ⚠️ GigaChat не вернул изображение")
            logger.warning(f"   💡 Возможно, модель GigaChat-Img недоступна")
            return None
                
        except AttributeError as e:
            logger.warning(f"   ⚠️ Ошибка доступа к атрибутам GigaChat: {e}")
            logger.warning(f"   💡 Убедитесь, что SDK версии 0.1.42+")
            return None
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка генерации изображения: {e}")
            logger.error(f"   💡 Проверьте доступность модели GigaChat-Img")
            return None


"""Умный клиент с автопереключением моделей при исчерпании токенов"""
class GigaChatSmartClient(GigaChatClient):
    
    MODELS_MAP = {
        'GigaChat': 'GigaChat',  # Lite
        'GigaChat-Max': 'GigaChat-Max',
        'GigaChat-Pro': 'GigaChat-Pro'
    }
    
    def __init__(self):
        super().__init__()
        self.settings = self._get_or_create_settings()
        # Устанавливаем текущую модель из настроек
        self.model = self.settings.current_model
        self._initialize_client()
    
    # ------------------------------------------------------------------
    # Rate limit helpers
    # ------------------------------------------------------------------
    def _get_cooldown_file_path(self, cooldown_key: str) -> Path:
        """Получить путь к файлу cooldown"""
        # Создаем безопасное имя файла из ключа
        safe_key = cooldown_key.replace(':', '_').replace('/', '_')
        cooldown_dir = Path(settings.BASE_DIR) / 'tmp' / 'cooldown'
        cooldown_dir.mkdir(parents=True, exist_ok=True)
        return cooldown_dir / f"{safe_key}.txt"
    
    def _get_cooldown_remaining(self, cooldown_key: str) -> int:
        """
        Получить оставшееся время cooldown через файловую систему.
        Возвращает количество секунд до окончания cooldown или 0 если cooldown не активен.
        """
        try:
            cooldown_file = self._get_cooldown_file_path(cooldown_key)
            
            # Если файл не существует - cooldown не активен
            if not cooldown_file.exists():
                return 0
            
            # Читаем время окончания cooldown из файла
            try:
                with open(cooldown_file, 'r', encoding='utf-8') as f:
                    cooldown_until = float(f.read().strip())
            except (ValueError, IOError) as e:
                logger.warning(f"⚠️ Не удалось прочитать cooldown из файла {cooldown_file}: {e}")
                # Удаляем поврежденный файл
                try:
                    cooldown_file.unlink()
                except:
                    pass
                return 0
            
            # Вычисляем оставшееся время
            remaining = int(cooldown_until - time.time())
            
            # Если cooldown истек - удаляем файл
            if remaining <= 0:
                try:
                    cooldown_file.unlink()
                except:
                    pass
                return 0
            
            return remaining
            
        except Exception as exc:
            logger.warning(f"⚠️ Не удалось прочитать cooldown {cooldown_key}: {exc}")
            return 0

    def _set_cooldown(self, cooldown_key: str, seconds: int, reason: str = "") -> None:
        """
        Установить cooldown через файловую систему.
        Сохраняет время окончания cooldown в файл.
        """
        try:
            cooldown_file = self._get_cooldown_file_path(cooldown_key)
            cooldown_until = time.time() + seconds
            
            # Создаем директорию если не существует
            cooldown_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Записываем время окончания cooldown в файл
            with open(cooldown_file, 'w', encoding='utf-8') as f:
                f.write(str(cooldown_until))
            
            logger.warning(
                f"⏳ Установлен cooldown {seconds}с для запросов GigaChat ({reason or '429 Too Many Requests'}) "
                f"через файловую систему: {cooldown_file.name}"
            )
            
            # Очищаем старые файлы cooldown (старше 1 часа)
            self._cleanup_old_cooldown_files()
            
        except Exception as exc:
            logger.error(f"❌ Не удалось установить cooldown для {cooldown_key}: {exc}")
    
    def _cleanup_old_cooldown_files(self) -> None:
        """Очищает старые файлы cooldown (старше 1 часа)"""
        try:
            cooldown_dir = Path(settings.BASE_DIR) / 'tmp' / 'cooldown'
            if not cooldown_dir.exists():
                return
            
            current_time = time.time()
            cleanup_threshold = 3600  # 1 час
            
            for cooldown_file in cooldown_dir.glob('*.txt'):
                try:
                    # Проверяем время модификации файла
                    file_mtime = cooldown_file.stat().st_mtime
                    if current_time - file_mtime > cleanup_threshold:
                        # Проверяем содержимое - если cooldown истек, удаляем
                        try:
                            with open(cooldown_file, 'r', encoding='utf-8') as f:
                                cooldown_until = float(f.read().strip())
                            if current_time >= cooldown_until:
                                cooldown_file.unlink()
                                logger.debug(f"🗑️ Удален истекший cooldown файл: {cooldown_file.name}")
                        except:
                            # Если файл поврежден или старый - удаляем
                            cooldown_file.unlink()
                            logger.debug(f"🗑️ Удален поврежденный cooldown файл: {cooldown_file.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка при очистке файла {cooldown_file}: {e}")
        except Exception as exc:
            logger.warning(f"⚠️ Ошибка при очистке старых cooldown файлов: {exc}")

    async def _acquire_rate_limit_lock(
        self,
        lock_key: str,
        lock_ttl: int,
        max_wait: int,
        task_label: str = "генерации",
    ) -> str:
        """
        Упрощенная версия без блокировки через кэш.
        Блокировка через DatabaseCache отключена для избежания проблем с MySQL.
        Теперь полагаемся только на cooldown механизм GigaChat API.
        """
        token = uuid.uuid4().hex
        logger.info(
            f"🔓 Блокировка через кэш отключена для {task_label}. "
            f"Используется только cooldown механизм GigaChat API."
        )
        return token

    def _release_rate_limit_lock(self, lock_key: str, token: str) -> None:
        """
        Упрощенная версия без освобождения блокировки через кэш.
        Блокировка через DatabaseCache отключена.
        """
        logger.debug(f"🔓 Блокировка {lock_key} не требуется (механизм отключен)")

    """Получить или создать настройки GigaChat"""
    def _get_or_create_settings(self):
        from .models import GigaChatSettings, GigaChatUsageStats
    
        def get_balance(model_name):
            stats = GigaChatUsageStats.objects.filter(model_name=model_name).first()
            return stats.tokens_remaining if stats else 0
    
        settings, created = GigaChatSettings.objects.get_or_create(pk=1)
    
        if created:
            settings.models_priority = ['GigaChat', 'GigaChat-Pro']  # GigaChat-Max отключен
            settings.current_model = 'GigaChat'
            settings.save()
            logger.info("Созданы настройки GigaChat по умолчанию: GigaChat (Lite)")
            return settings
    
        # Устанавливаем приоритетную цепочку
        priority_chain = ['GigaChat', 'GigaChat-Pro']  # GigaChat-Max отключен
        settings.models_priority = priority_chain
    
        # Проверяем баланс и выбираем первую доступную модель
        target_model = None
        for model in priority_chain:
            balance = get_balance(model)
            threshold = 100_000 if 'Pro' in model else (1_000_000 if 'GigaChat' == model else 100_000)
            if balance > threshold:
                target_model = model
                logger.info(f"🔋 Доступна модель: {model} (баланс: {balance:,})")
                break
    
        if not target_model:
            # Все модели ниже порога — выбираем Max как последнюю
            target_model = 'GigaChat-Max'
            logger.critical("🔴 Все модели ниже порога, принудительно используем GigaChat-Max")
    
        # Только если модель изменилась — обновляем
        if settings.current_model != target_model:
            logger.warning(f"🔄 Переключение: {settings.current_model} → {target_model} (баланс: {get_balance(target_model):,})")
            settings.current_model = target_model
            settings.save()
        else:
            logger.info(f"✅ Текущая модель {target_model} остаётся активной (баланс: {get_balance(target_model):,})")
    
        return settings
    
    """Переключиться на следующую доступную модель"""
    def _find_available_model(self, skip_models: List[str] = None) -> Optional[str]:
        """
        Находит доступную модель (без cooldown и с балансом токенов).
        
        Args:
            skip_models: Список моделей, которые нужно пропустить
            
        Returns:
            Имя доступной модели или None
        """
        skip_models = skip_models or []
        # GigaChat-Max отключен - не используется
        models_chain = self.settings.models_priority or ['GigaChat', 'GigaChat-Pro']
        # Фильтруем Max из списка
        models_chain = [m for m in models_chain if m != 'GigaChat-Max']
        
        for model in models_chain:
            if model in skip_models:
                continue
            
            if not self._model_enabled(model):
                continue
            
            # Проверяем баланс токенов
            if not self._model_has_quota(model):
                logger.debug(f"   ⏭️ Модель {model} пропущена: нет квоты/баланса")
                continue
            
            # Проверяем cooldown
            cooldown_key = f"gigachat:{model}:429"
            cooldown_remaining = self._get_cooldown_remaining(cooldown_key)
            if cooldown_remaining > 0:
                logger.debug(f"   ⏭️ Модель {model} пропущена: cooldown {cooldown_remaining}s")
                continue
            
            # Модель доступна!
            return model
        
        return None
    
    def _switch_to_next_model(self):
        try:
            current_index = self.settings.models_priority.index(self.settings.current_model)
        except ValueError:
            # Текущая модель не в списке приоритетов - начинаем с первой
            current_index = -1
        
        next_index = (current_index + 1) % len(self.settings.models_priority)
        next_model = self.settings.models_priority[next_index]
        
        logger.info(f"🔄 Переключение с {self.settings.current_model} на {next_model}")
        self.settings.current_model = next_model
        self.settings.save()
        self.model = next_model
        self._initialize_client()

    def _model_limit_for(self, model_name: str) -> int:
        if "Pro" in model_name:
            return self.settings.pro_daily_limit
        if "Max" in model_name:
            return self.settings.max_daily_limit
        if model_name == "GigaChat":
            return self.settings.lite_daily_limit
        return 0

    def _price_for_model(self, model_name: str) -> Decimal:
        if "Pro" in model_name:
            return self.settings.price_pro
        if "Max" in model_name:
            return self.settings.price_max
        if model_name == "GigaChat":
            return self.settings.price_lite
        if "Embeddings" in model_name:
            return self.settings.price_embeddings
        return self.settings.price_pro

    def _get_usage_stats(self, model_name: str):
        stats, _ = GigaChatUsageStats.objects.get_or_create(model_name=model_name)
        stats.reset_daily_counters_if_needed(save=True)
        return stats

    def _model_has_quota(self, model_name: str) -> bool:
        limit = self._model_limit_for(model_name)
        if limit <= 0:
            return True
        stats = self._get_usage_stats(model_name)
        return stats.tokens_used_today < limit

    def _filter_models_by_quota(self, models_chain):
        allowed = [model for model in models_chain if self._model_has_quota(model)]
        if not allowed:
            raise Exception("Все модели GigaChat достигли дневного лимита токенов.")
        return allowed

    @staticmethod
    def _estimate_tokens(text: Optional[str]) -> int:
        if not text:
            return 0
        # Примерная оценка: 1 токен ≈ 4 символам
        return max(1, len(text) // 4)

    def _register_usage_for_request(self, prompt_text: str, response_text: str) -> None:
        try:
            tokens = self._estimate_tokens(prompt_text) + self._estimate_tokens(response_text)
            stats = self._get_usage_stats(self.settings.current_model)
            stats.register_usage(tokens, self._price_for_model(self.settings.current_model))
        except Exception as exc:
            logger.warning("⚠️ Не удалось зафиксировать расход токенов: %s", exc)

    def _task_failure_cache_key(self, task_type: str) -> str:
        return f"gigachat:task_fail:{task_type}"

    def _check_task_circuit(self, task_type: str) -> None:
        limit = self.settings.task_failure_limit
        if limit <= 0:
            return
        data = cache.get(self._task_failure_cache_key(task_type))
        if data and data.get("count", 0) >= limit:
            raise Exception(
                f"GigaChat временно отключён для задачи '{task_type}': превышен лимит ошибок. "
                f"Подождите {self.settings.task_failure_window} минут."
            )

    def _register_task_failure(self, task_type: str) -> None:
        limit = self.settings.task_failure_limit
        if limit <= 0:
            return
        key = self._task_failure_cache_key(task_type)
        data = cache.get(key) or {"count": 0}
        data["count"] = data.get("count", 0) + 1
        cache.set(key, data, timeout=self.settings.task_failure_window * 60)

    def _reset_task_failure(self, task_type: str) -> None:
        cache.delete(self._task_failure_cache_key(task_type))
    
    def _model_enabled(self, model_name: str) -> bool:
        # GigaChat-Max отключен - не используется
        if model_name == "GigaChat-Max":
            return False
        if model_name == "GigaChat":
            return self.settings.lite_enabled
        if "Pro" in model_name:
            return self.settings.pro_enabled
        if "Max" in model_name:
            return False  # Все модели Max отключены
        if "Embeddings" in model_name:
            return self.settings.embeddings_enabled
        return True

    def _ordered_text_models(self) -> List[str]:
        # GigaChat-Max отключен - не используется
        priority = self.settings.models_priority or ['GigaChat', 'GigaChat-Pro']
        ordered = [model for model in priority if self._model_enabled(model) and model != 'GigaChat-Max']
        for fallback in ['GigaChat', 'GigaChat-Pro']:
            if fallback not in ordered and self._model_enabled(fallback) and fallback != 'GigaChat-Max':
                ordered.append(fallback)
        return ordered

    def _build_model_chain(self, preferred_model: str, task_type: str) -> List[str]:
        if preferred_model == 'GigaChat-Embeddings':
            return ['GigaChat-Embeddings'] if self._model_enabled('GigaChat-Embeddings') else []

        if task_type in STRICT_TASK_TYPES:
            chain = FALLBACK_CHAINS.get(preferred_model, self._ordered_text_models())
            return [model for model in chain if self._model_enabled(model)]

        ordered = self._ordered_text_models()
        if preferred_model not in ordered and self._model_enabled(preferred_model):
            ordered.append(preferred_model)
        seen = []
        for model in ordered:
            if model not in seen and self._model_enabled(model):
                seen.append(model)
        return seen
    
    
    """Оптимизированный вызов GigaChat с умным выбором модели"""
    def chat_optimized(self, message: str, task_type: str = 'general', system_prompt: str = None) -> str:
        # Шаг 1: Определяем оптимальную модель для задачи
        optimal_model = TASK_TO_MODEL.get(task_type, 'GigaChat-Pro')
        
        logger.info(f"📋 Задача: {task_type} → Оптимальная модель: {optimal_model}")

        # Проверяем circuit breaker
        self._check_task_circuit(task_type)
        
        # Шаг 2: Получаем цепочку моделей с учётом стоимости/лимитов
        model_chain = self._build_model_chain(optimal_model, task_type)
        if not model_chain:
            raise Exception("Нет доступных моделей GigaChat для текущей задачи")

        fallback_chain = self._filter_models_by_quota(model_chain)
        
        # Шаг 3: Переключаемся на первую модель из цепочки (приоритет дешевле)
        selected_model = fallback_chain[0]
        
        # Шаг 4: Переключаемся на выбранную модель если нужно
        if self.settings.current_model != selected_model:
            logger.info(f"🔄 Переключение: {self.settings.current_model} → {selected_model}")
            self.settings.current_model = selected_model
            self.settings.save()
            self.model = selected_model
            self._initialize_client()
        
        # Шаг 5: Выполняем запрос через существующий метод chat()
        # Он содержит РЕАКТИВНУЮ защиту (при ошибке 402 автопереключение)
        try:
            result = self.chat(message, system_prompt)
            logger.info(f"✅ Задача {task_type} выполнена моделью {selected_model}")
            self._reset_task_failure(task_type)
            return result
        except Exception as e:
            self._register_task_failure(task_type)
            logger.error(f"❌ Ошибка в chat_optimized: {e}")
            raise
            
    """Переопределенный метод с автопереключением моделей"""
    def chat(self, message: str, system_prompt: str = None) -> str:
        from .models import GigaChatUsageStats
        
        max_attempts = len(self.settings.models_priority)
        
        for attempt in range(max_attempts):
            if not self._model_has_quota(self.settings.current_model):
                logger.warning(
                    "⛔ Дневной лимит для модели %s исчерпан, переключаемся на следующую",
                    self.settings.current_model,
                )
                self._switch_to_next_model()
                continue
            
            # Проверяем cooldown для текущей модели (если был 429)
            cooldown_key = f"gigachat:{self.settings.current_model}:429"
            cooldown_remaining = self._get_cooldown_remaining(cooldown_key)
            if cooldown_remaining > 0:
                logger.info(f"⏳ Модель {self.settings.current_model} в cooldown ({cooldown_remaining}s), переключаемся")
                if self.settings.auto_switch_enabled and attempt < max_attempts - 1:
                    # Пробуем найти модель без cooldown и с балансом
                    next_model = self._find_available_model(skip_models=[self.settings.current_model])
                    if next_model:
                        logger.info(f"🔄 Переключение с {self.settings.current_model} на {next_model} (cooldown истек или модель доступна)")
                        self.settings.current_model = next_model
                        self.settings.save()
                        self._initialize_client()
                        continue
                    else:
                        # Нет доступных моделей - ждём окончания cooldown
                        logger.warning(f"⏳ Все модели в cooldown или без баланса. Ждём {min(cooldown_remaining, 60)}s...")
                        import time
                        time.sleep(min(cooldown_remaining, 60))
                        continue
                else:
                    # Нет возможности переключиться - ждём
                    import time
                    time.sleep(min(cooldown_remaining, 60))
            
            try:
                # Выполняем запрос через родительский метод
                result = super().chat(message, system_prompt)
                
                # ВАЖНО: Регистрируем использование токенов ПЕРЕД возвратом результата
                try:
                    self._register_usage_for_request(message, result)
                    logger.debug(f"✅ Использование токенов зарегистрировано для модели {self.settings.current_model}")
                except Exception as reg_exc:
                    logger.error(f"❌ Ошибка регистрации токенов: {reg_exc}", exc_info=True)
                    # НЕ прерываем выполнение - продолжаем даже если регистрация не удалась
                
                # Обновляем статистику успешного запроса
                stats, _ = GigaChatUsageStats.objects.get_or_create(
                    model_name=self.settings.current_model
                )
                stats.total_requests += 1
                stats.successful_requests += 1
                stats.save()
                
                return result
                
            except RateLimitCooldown as rlc:
                # Специальная обработка RateLimitCooldown исключения из базового метода
                error_str = str(rlc)
                record_integration_error('gigachat', '429', error_str, severity='warning', context={'model': self.settings.current_model})
                logger.warning(f"⚠️ Модель {self.settings.current_model}: Rate Limit (429) - {rlc.reason}")
                
                # Получаем статистику для текущей модели
                stats, _ = GigaChatUsageStats.objects.get_or_create(
                    model_name=self.settings.current_model
                )
                stats.total_requests += 1
                
                # Устанавливаем cooldown для этой модели
                cooldown_seconds = rlc.retry_after
                self._set_cooldown(
                    f"gigachat:{self.settings.current_model}:429",
                    cooldown_seconds,
                    reason=rlc.reason or "429 Too Many Requests"
                )
                
                if attempt < max_attempts - 1:
                    logger.info(f"🔄 Попытка {attempt + 2}/{max_attempts} после Rate Limit (cooldown {cooldown_seconds}s)")
                    # Задержка перед следующей попыткой
                    import time
                    time.sleep(min(10, cooldown_seconds))
                    
                    # Пробуем переключиться на другую модель если есть
                    if self.settings.auto_switch_enabled:
                        self._switch_to_next_model()
                        stats.save()  # Сохраняем только total_requests, без failed_requests
                        continue
                
                # Если не удалось переключиться - считаем это ошибкой
                stats.failed_requests += 1
                stats.save()
                
                # Вычисляем время, когда можно повторить запрос
                from datetime import datetime, timedelta
                retry_after = datetime.now() + timedelta(seconds=cooldown_seconds)
                retry_time_str = retry_after.strftime("%H:%M:%S")
                
                error_msg = (
                    f"Достигнут лимит запросов GigaChat (модель: {self.settings.current_model}). "
                    f"Подождите {cooldown_seconds} секунд. "
                    f"Повторите запрос после {retry_time_str}"
                )
                raise Exception(error_msg)
                
            except Exception as e:
                error_str = str(e)
                error_repr = repr(e)
                
                # Получаем статистику для текущей модели
                stats, _ = GigaChatUsageStats.objects.get_or_create(
                    model_name=self.settings.current_model
                )
                stats.total_requests += 1
                
                # Проверяем код ошибки 402 (Payment Required)
                if '402' in error_str or 'Payment Required' in error_str:
                    record_integration_error('gigachat', '402', error_str, severity='error', context={'model': self.settings.current_model})
                    logger.warning(f"⚠️ Модель {self.settings.current_model}: закончились токены (ошибка 402)")
                    
                    if self.settings.auto_switch_enabled and attempt < max_attempts - 1:
                        # НЕ считаем это ошибкой - это нормальное переключение моделей
                        # Просто логируем и переключаемся
                        logger.info(f"🔄 Автопереключение с {self.settings.current_model} на следующую модель (попытка {attempt + 2}/{max_attempts})")
                        self._switch_to_next_model()
                        stats.save()  # Сохраняем только total_requests, без failed_requests
                        continue
                    else:
                        # Это реальная ошибка - нет возможности переключиться
                        stats.failed_requests += 1
                        stats.save()
                        raise Exception(f"Закончились токены на всех моделях GigaChat")
                        
                elif '429' in error_str or 'Too Many Requests' in error_str or 'rate limit' in error_str.lower():
                    # Ошибка 429 - Rate Limit, это временная проблема
                    record_integration_error('gigachat', '429', error_str, severity='warning', context={'model': self.settings.current_model})
                    logger.warning(f"⚠️ Модель {self.settings.current_model}: Rate Limit (429)")
                    
                    # Устанавливаем cooldown для этой модели (увеличиваем до 2 минут)
                    cooldown_seconds = 120  # 2 минуты cooldown для 429
                    self._set_cooldown(
                        f"gigachat:{self.settings.current_model}:429",
                        cooldown_seconds,
                        reason="429 Too Many Requests"
                    )
                    
                    if attempt < max_attempts - 1:
                        # Пробуем переключиться на другую модель или подождать
                        logger.info(f"🔄 Попытка {attempt + 2}/{max_attempts} после Rate Limit")
                        # Небольшая задержка перед следующей попыткой
                        import time
                        time.sleep(min(5, cooldown_seconds))
                        
                        # Пробуем переключиться на другую модель если есть
                        if self.settings.auto_switch_enabled:
                            self._switch_to_next_model()
                            stats.save()  # Сохраняем только total_requests, без failed_requests
                            continue
                    
                    # Если не удалось переключиться - считаем это ошибкой
                    stats.failed_requests += 1
                    stats.save()
                    raise
                    
                else:
                    # Неизвестная ошибка - считаем её реальной ошибкой
                    record_integration_error('gigachat', 'unknown', error_str, severity='warning', context={'model': self.settings.current_model})
                    stats.failed_requests += 1
                    stats.save()
                    # Пробрасываем дальше
                    raise
        
        raise Exception("Все попытки использования GigaChat моделей исчерпаны")
    
    """Асинхронная генерация изображения через GigaChat"""
    async def generate_and_save_image(self, prompt: str, style_prompt: str = None) -> Optional[str]:
        from gigachat.models import Chat, Messages, MessagesRole
        import base64
        import uuid
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        from django.utils import timezone
        from bs4 import BeautifulSoup
        import asyncio
    
        logger.info(f"🎨 Асинхронная генерация изображения: {prompt[:50]}...")
    
        # Сохраняем оригинальную модель
        original_model = self.model
        lock_token = None
        
        try:
            # Проверяем глобальный cooldown перед попыткой
            cooldown_remaining = self._get_cooldown_remaining(IMAGE_RATE_LIMIT_COOLDOWN_KEY)
            if cooldown_remaining > 0:
                record_integration_error(
                    'gigachat',
                    '429_image',
                    f'Активен cooldown {cooldown_remaining}s перед генерацией изображения',
                    severity='warning',
                )
                raise RateLimitCooldown(
                    cooldown_remaining,
                    reason="активен глобальный cooldown после 429"
                )

            # Блокируем окно генерации, чтобы ограничить параллельные запросы
            lock_token = await self._acquire_rate_limit_lock(
                IMAGE_RATE_LIMIT_LOCK_KEY,
                IMAGE_RATE_LIMIT_LOCK_TTL,
                IMAGE_RATE_LIMIT_MAX_WAIT,
                task_label="генерации изображений (GigaChat)"
            )

            # Получаем приоритеты моделей для генерации изображений
            optimal_model = TASK_TO_MODEL.get('image_generation', 'GigaChat-Pro')
            fallback_chain = FALLBACK_CHAINS.get(optimal_model, ['GigaChat-Pro', 'GigaChat-Max'])
            timeout_sequence = [60, 90, 120]  # секунды ожидания для повторов внутри одной модели
            
            logger.info(f"   📋 Задача: image_generation → Приоритет моделей: {fallback_chain}")
        
            # Пробуем каждую модель из цепочки приоритетов
            last_error = None
            for model_to_try in fallback_chain:
                # Переключаемся на текущую модель из цепочки
                self.model = model_to_try
                self._initialize_client()
                logger.info(f"   🔄 Попытка генерации через {self.model}...")

                for attempt_index, timeout_seconds in enumerate(timeout_sequence, start=1):
                    logger.info(
                        f"   ⏱️ Попытка {attempt_index}/{len(timeout_sequence)} для {model_to_try} "
                        f"(таймаут {timeout_seconds}s)"
                    )
                    try:
                        # Формируем сообщения
                        messages = []
                        if style_prompt:
                            messages.append(Messages(
                                role=MessagesRole.SYSTEM,
                                content=style_prompt
                            ))
                        messages.append(Messages(
                            role=MessagesRole.USER,
                            content=f"Нарисуй {prompt}"
                        ))
                        
                        # КРИТИЧНО: function_call="auto" для активации text2image
                        payload = Chat(
                            messages=messages,
                            function_call="auto"
                        )
                        
                        # Асинхронный вызов с контролем таймаута
                        response = await asyncio.wait_for(
                            asyncio.to_thread(self.client.chat, payload),
                            timeout=timeout_seconds
                        )
                        content = response.choices[0].message.content
                        logger.info(f"   📥 Ответ от GigaChat получен")
                        
                        # Извлекаем UUID изображения из <img src="uuid">
                        soup = BeautifulSoup(content, "html.parser")
                        img_tag = soup.find('img')
                        if not img_tag:
                            raise Exception("Нет <img> тега в ответе")
                        file_id = img_tag.get('src')
                        if not file_id:
                            raise Exception("Нет src атрибута в <img>")
                        logger.info(f"   🆔 UUID изображения: {file_id}")
                        
                        # Скачиваем изображение с таймаутом
                        image = await asyncio.wait_for(
                            asyncio.to_thread(self.client.get_image, file_id),
                            timeout=timeout_seconds
                        )
                        image_data = base64.b64decode(image.content)
                        logger.info(f"   📥 Изображение скачано, размер: {len(image_data)} байт")
                        
                        # Сохраняем файл
                        now = timezone.now()
                        filename = f"gigachat_{uuid.uuid4().hex[:12]}.jpg"
                        filepath = f"images/{now.year}/{now.month:02d}/{filename}"
                        
                        try:
                            saved_path = await asyncio.to_thread(
                                default_storage.save, filepath, ContentFile(image_data)
                            )
                        except OSError as storage_error:
                            if getattr(storage_error, 'errno', None) == errno.ENOSPC:
                                record_integration_error(
                                    'storage',
                                    'ENOSPC',
                                    'Недостаточно места при сохранении gigachat изображения',
                                    severity='error',
                                )
                            raise
                        logger.info(f"   ✅ Изображение сохранено через {self.model}: {saved_path}")
                        
                        # Успешно сгенерировали - возвращаем результат
                        return saved_path
                    
                    except asyncio.TimeoutError as e:
                        last_error = e
                        logger.warning(
                            f"   ⏳ Таймаут {timeout_seconds}s при генерации через {model_to_try} "
                            f"(попытка {attempt_index})."
                        )
                        if attempt_index < len(timeout_sequence):
                            await asyncio.sleep(2)
                            continue
                        else:
                            logger.warning(f"   ⛔ Максимум попыток для {model_to_try} исчерпан (таймауты).")
                            break
                    except Exception as e:
                        last_error = e
                        error_msg = str(e)
                        logger.warning(f"   ⚠️ Ошибка генерации через {model_to_try}: {error_msg}")
                        
                        # Повторяем попытку при типичных сетевых ошибках
                        retryable = any(
                            phrase in error_msg.lower()
                            for phrase in [
                                'timed out',
                                'timeout',
                                'temporarily unavailable',
                                'connection aborted',
                                'connection reset',
                                'bad gateway',
                                'service unavailable',
                                'ssl handshake',
                                '502',
                                '503',
                                '504',
                                '429',
                            ]
                        )
                        if retryable and attempt_index < len(timeout_sequence):
                            logger.info(f"   🔁 Ошибка считается временной, повторяем попытку после паузы...")
                            await asyncio.sleep(2)
                            continue
                        
                        # Ошибки 402/429 дают шанс перейти к следующей модели
                        normalized_msg = error_msg.lower()
                        if (
                            '429' in normalized_msg
                            or 'too many requests' in normalized_msg
                        ):
                            record_integration_error('gigachat', '429_image', normalized_msg, severity='warning')
                            self._set_cooldown(
                                IMAGE_RATE_LIMIT_COOLDOWN_KEY,
                                IMAGE_RATE_LIMIT_COOLDOWN,
                                reason="429 Too Many Requests"
                            )
                            raise RateLimitCooldown(
                                IMAGE_RATE_LIMIT_COOLDOWN,
                                reason="429 Too Many Requests"
                            )

                        if '402' in error_msg or 'balance' in normalized_msg:
                            logger.info(f"   🔄 Переходим к следующей модели после ошибки: {error_msg}")
                            break
                        
                        # Критические ошибки — прекращаем цепочку моделей
                        logger.error(f"   ❌ Критическая ошибка, прекращаем попытки: {error_msg}")
                        return None
                
                # Если дошли сюда — текущая модель не справилась, пробуем следующую
                continue
            
            # Если дошли сюда - все модели не сработали
            if last_error:
                logger.error(f"   ❌ Не удалось сгенерировать изображение ни через одну модель. Последняя ошибка: {last_error}")
            else:
                logger.error(f"   ❌ Не удалось сгенерировать изображение: неизвестная ошибка")
            
            return None
        
        finally:
            if lock_token:
                self._release_rate_limit_lock(IMAGE_RATE_LIMIT_LOCK_KEY, lock_token)
            # Возвращаем оригинальную модель
            self.model = original_model
            self._initialize_client()
            logger.info(f"   🔄 Возвращено на модель {self.model}")
    
    """Получить векторное представление текста через GigaChat-Embeddings"""
    @rate_limit_retry(max_retries=3, base_delay=5)
    def get_embeddings(self, text: str) -> List[float]:
        """
        Получить векторное представление текста через GigaChat-Embeddings
        
        Args:
            text: Текст для векторизации
            
        Returns:
            List[float]: Вектор embeddings (обычно 1024 измерения)
            
        Raises:
            Exception: При ошибке API или недоступности сервиса
        """
        if not self.client:
            raise Exception("GigaChat клиент не инициализирован")
        
        # Валидация: проверка на пустоту и минимальную длину
        if not text or not text.strip():
            logger.warning("Пустой текст для embeddings, возвращаем пустой вектор")
            return []
        
        text_clean = text.strip()
        if len(text_clean) < 10:
            logger.warning(f"Слишком короткий текст для embeddings ({len(text_clean)} символов, минимум 10)")
            return []
        
        try:
            # Сохраняем оригинальную модель
            original_model = self.model
            
            # Переключаемся на Embeddings модель
            self.model = 'Embeddings'
            self._initialize_client()
            
            logger.info(f"📊 Генерация embeddings для текста ({len(text)} символов)...")
            
            # Вызываем метод embeddings из SDK
            # Совместимость с разными версиями SDK
            try:
                # Попытка 1: Новый API (SDK >= 0.1.25)
                response = self.client.embeddings(
                    model="Embeddings",
                    input=[text[:8000]]
                )
            except (TypeError, Exception) as e:
                logger.warning(f"   Попытка 1 не удалась: {e}")
                
                try:
                    # Попытка 2: Прямой вызов с текстами
                    response = self.client.embeddings([text[:8000]])
                except Exception as e2:
                    logger.warning(f"   Попытка 2 не удалась: {e2}")
                    
                    try:
                        # Попытка 3: Через POST запрос напрямую
                        logger.info("   🔄 Используем прямой API вызов...")
                        response = self.client.stream(
                            model="Embeddings",
                            messages=[{"role": "user", "content": text[:8000]}]
                        )
                    except Exception as e3:
                        logger.error(f"   ❌ Все попытки failed: {e3}")
                        raise Exception(f"Embeddings API недоступен в текущей версии SDK")
            
            # Извлекаем вектор из ответа
            if response and hasattr(response, 'data') and len(response.data) > 0:
                embedding = response.data[0].embedding
                logger.info(f"   ✅ Embedding получен: {len(embedding)} измерений")
                
                # Возвращаем оригинальную модель
                self.model = original_model
                self._initialize_client()
                
                return embedding
            else:
                logger.error("   ❌ Пустой ответ от Embeddings API")
                
                # Возвращаем оригинальную модель
                self.model = original_model
                self._initialize_client()
                
                return []
                
        except Exception as e:
            logger.error(f"   ❌ Ошибка получения embeddings: {e}")
            
            # Возвращаем оригинальную модель в случае ошибки
            try:
                self.model = original_model
                self._initialize_client()
            except:
                pass
            
            raise Exception(f"Ошибка GigaChat Embeddings API: {str(e)}")


# Singleton instance
_gigachat_client = None

# Получить умный клиент GigaChat с автопереключением
def get_gigachat_client():
    """Получить умный клиент GigaChat с автопереключением"""
    global _gigachat_client
    if _gigachat_client is None:
        _gigachat_client = GigaChatSmartClient()
    return _gigachat_client


def check_and_update_gigachat_balance(client=None):
    """
    Проверяет и обновляет баланс токенов GigaChat в БД.
    Используется для ручной проверки баланса (например, в админке).
    
    Args:
        client: Экземпляр GigaChatSmartClient. Если не указан, создается новый.
    
    Returns:
        Dict[str, int]: Словарь с балансом токенов для каждой модели
    """
    if client is None:
        client = get_gigachat_client()
    
    balances = client.get_balance()
    for model_name, tokens_remaining in balances.items():
        stats, _ = GigaChatUsageStats.objects.get_or_create(
            model_name=model_name,
            defaults={'tokens_remaining': tokens_remaining}
        )
        stats.tokens_remaining = tokens_remaining
        stats.save()
    
    logger.info(f"Баланс обновлен: {balances}")
    return balances


# Глобальная функция для получения embeddings через GigaChat
def get_embeddings(text: str) -> List[float]:
    """
    Глобальная функция для получения embeddings через GigaChat
    
    Args:
        text: Текст для векторизации
        
    Returns:
        List[float]: Вектор embeddings или пустой список при ошибке
        
    Example:
        >>> from Asistent.gigachat_api import get_embeddings
        >>> vector = get_embeddings("Как стать автором?")
        >>> len(vector)
        1024
    """
    try:
        client = get_gigachat_client()
        return client.get_embeddings(text)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_embeddings(): {e}")
        return []


# Пакетная генерация embeddings для экономии времени и токенов
def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Пакетная генерация embeddings для экономии времени и токенов
    
    Args:
        texts: Список текстов для векторизации
        
    Returns:
        List[List[float]]: Список векторов embeddings
        
    Example:
        >>> from Asistent.gigachat_api import get_embeddings_batch
        >>> texts = ["Первый текст", "Второй текст", "Третий текст"]
        >>> vectors = get_embeddings_batch(texts)
        >>> len(vectors)
        3
        >>> len(vectors[0])
        1024
    """
    if not texts:
        return []
    
    try:
        client = get_gigachat_client()
        
        if not client or not client.client:
            logger.error("GigaChat клиент не инициализирован")
            return [[] for _ in texts]
        
        # Фильтруем и валидируем тексты
        valid_texts = []
        valid_indices = []
        
        for i, text in enumerate(texts):
            if text and text.strip() and len(text.strip()) >= 10:
                valid_texts.append(text.strip()[:8000])  # Обрезаем до 8K
                valid_indices.append(i)
            else:
                logger.warning(f"Пропуск текста {i}: пустой или слишком короткий")
        
        if not valid_texts:
            logger.warning("Нет валидных текстов для batch embeddings")
            return [[] for _ in texts]
        
        logger.info(f"📊 Batch генерация embeddings для {len(valid_texts)} текстов...")
        
        # Сохраняем оригинальную модель
        original_model = client.model
        client.model = 'Embeddings'
        client._initialize_client()
        
        try:
            # Пакетный запрос к API
            # Совместимость с разными версиями SDK
            try:
                # Новый API (SDK >= 0.1.25)
                response = client.client.embeddings(
                    model="Embeddings",
                    input=valid_texts
                )
            except TypeError:
                # Старый API (SDK < 0.1.25)
                try:
                    from gigachat.models import Embeddings as EmbeddingsModel
                    response = client.client.embeddings(
                        EmbeddingsModel(input=valid_texts)
                    )
                except Exception as e2:
                    logger.error(f"   ❌ Не удалось вызвать batch embeddings API: {e2}")
                    raise
            
            if response and hasattr(response, 'data'):
                # Создаём результирующий список
                results = [[] for _ in texts]
                
                # Заполняем векторами только валидные позиции
                for i, data_item in enumerate(response.data):
                    if i < len(valid_indices):
                        original_idx = valid_indices[i]
                        results[original_idx] = data_item.embedding
                
                success_count = sum(1 for r in results if r)
                logger.info(f"   ✅ Batch успешно: {success_count}/{len(texts)} векторов")
                
                return results
            else:
                logger.error("   ❌ Пустой ответ от Batch Embeddings API")
                return [[] for _ in texts]
                
        finally:
            # Возвращаем оригинальную модель
            client.model = original_model
            client._initialize_client()
            
    except Exception as e:
        logger.error(f"❌ Ошибка batch embeddings: {e}")
        # Fallback: генерируем по одному
        logger.info("   🔄 Fallback: генерация по одному...")
        return [get_embeddings(text) for text in texts]


# Вызов GigaChat API для чат-бота
def call_gigachat_api(prompt: str, system_prompt: str = None) -> Dict:
    """
    Вызов GigaChat API для чат-бота с умным выбором модели
    
    Использует task_type='chatbot' → GigaChat-Max для качественных ответов
    
    Args:
        prompt: Вопрос пользователя
        system_prompt: Системный промпт (контекст)
    
    Returns:
        Dict с ключами: success (bool), text (str), error (str)
    """
    try:
        client = get_gigachat_client()
        
        if not client or not client.client:
            logger.warning("GigaChat client not available")
            return {
                'success': False,
                'text': '',
                'error': 'GigaChat API недоступен'
            }
        
        # Используем chat_optimized с task_type='chatbot'
        # Это автоматически выберет GigaChat-Max из TASK_TO_MODEL
        response_text = client.chat_optimized(
            message=prompt,
            task_type='chatbot',  # ← Умный выбор модели
            system_prompt=system_prompt
        )
        
        if response_text:
            return {
                'success': True,
                'text': response_text,
                'error': None
            }
        else:
            return {
                'success': False,
                'text': '',
                'error': 'Пустой ответ от GigaChat'
            }
            
    except Exception as e:
        logger.error(f"Ошибка вызова GigaChat API: {e}")
        return {
            'success': False,
            'text': '',
            'error': str(e)
        }
