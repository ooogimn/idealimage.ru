"""
Автоматический фиксер медиа для статей
Скачивает и привязывает изображения/видео к статьям если они отсутствуют
"""
import os
import requests
import logging
from typing import Optional, Tuple
from django.core.files.base import ContentFile
from django.conf import settings
from django.utils.text import slugify
import hashlib
from PIL import Image
from io import BytesIO
from .prompt_registry import PromptRegistry
from .gigachat_api import RateLimitCooldown

logger = logging.getLogger(__name__)


class AutoMediaFixer:
    """Автоматический фиксер медиа для статей"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.max_file_size = 10 * 1024 * 1024  # 10 MB
        self.min_width = 400  # Минимальная ширина изображения
        self.min_height = 300  # Минимальная высота
    
    def fix_missing_media(
        self,
        post,
        is_superuser: bool = False,
        custom_image_prompt: Optional[str] = None,
        strategy: str = "download",
    ) -> Tuple[bool, str]:
        """
        Исправляет отсутствующее медиа в статье
        
        Args:
            post: Объект статьи (Post model)
            is_superuser: Режим суперюзера (генерация через GigaChat)
            strategy: download | generate (по умолчанию download)
        
        Returns:
            Tuple (success, message)
        """
        logger.info(f"🔧 Попытка исправить медиа для статьи: {post.title} (superuser={is_superuser})")
        strategy = (strategy or "download").lower()
        if strategy not in {"download", "generate"}:
            strategy = "download"
        
        # Проверяем есть ли уже медиа
        if self._has_valid_media(post):
            return True, "Медиа уже присутствует"
        
        # Если выбран сценарий генерации — пробуем с GigaChat, затем переходим к поиску
        if strategy == "generate" or is_superuser:
            success, message, _ = self._generate_image_with_gigachat(
                post,
                custom_image_prompt=custom_image_prompt,
                attach_to_post=True,
            )
            if success:
                logger.info("✅ Изображение сгенерировано через GigaChat.")
                return True, message

            logger.warning(f"❌ Генерация не удалась ({message}). Переходим к поиску изображения.")

            search_success, search_message = self._try_find_and_download_image(post)
            return (True, search_message) if search_success else (False, search_message)

        # Базовый сценарий: ищем подходящее изображение (внешние источники → локальные → fallback)
        success, message = self._try_find_and_download_image(post)
        return (True, message) if success else (False, message)
    
    def generate_new_image(self, post, custom_image_prompt: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Генерирует новое изображение через GigaChat, не заменяя текущее автоматически.
        Возвращает (success, message, new_filepath)
        """
        return self._generate_image_with_gigachat(
            post,
            custom_image_prompt=custom_image_prompt,
            attach_to_post=False
        )
    
    def _has_valid_media(self, post) -> bool:
        """Проверяет есть ли валидное медиа"""
        # Проверка video_url
        if hasattr(post, 'video_url') and post.video_url:
            logger.info(f"   ✓ Есть video_url: {post.video_url}")
            return True
        
        # Проверка video файла
        if hasattr(post, 'kartinka') and post.kartinka:
            if post.kartinka.name:
                name_lower = post.kartinka.name.lower()
                if any(name_lower.endswith(ext) for ext in ['.mp4', '.webm', '.mov']):
                    # Проверяем существование файла
                    if hasattr(post.kartinka, 'path'):
                        if os.path.exists(post.kartinka.path):
                            logger.info(f"   ✓ Есть видео-файл: {post.kartinka.name}")
                            return True
        
        # Проверка изображения
        if hasattr(post, 'kartinka') and post.kartinka:
            if hasattr(post.kartinka, 'path'):
                if os.path.exists(post.kartinka.path):
                    logger.info(f"   ✓ Есть изображение: {post.kartinka.name}")
                    return True
        
        logger.info(f"   ✗ Медиа отсутствует")
        return False
    
    def _generate_image_with_gigachat(
        self,
        post,
        custom_image_prompt: Optional[str] = None,
        attach_to_post: bool = True,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Генерация изображения через GigaChat PRO/MAX
        Только для суперюзеров и SEO оптимизации
        
        Args:
            post: Объект статьи
        
        Returns:
            Tuple (success, message)
        """
        logger.info(f"   🎨 ГЕНЕРАЦИЯ изображения через GigaChat (приоритет: PRO → MAX → Lite)...")
        
        try:
            from .gigachat_api import get_gigachat_client
            
            gigachat = get_gigachat_client()
            
            # Если передан кастомный промпт — используем его приоритетно
            if custom_image_prompt:
                prompt = custom_image_prompt
            else:
                # Формируем промпт на основе статьи (обратная совместимость)
                # Если это гороскоп — формируем строгий промпт (мужчина+женщина, Москва, сезон)
                if isinstance(getattr(post, 'title', ''), str) and 'Гороскоп для' in post.title:
                    prompt = self._build_horoscope_prompt(post)
                else:
                    category_name = post.category.title if post.category else 'lifestyle'
                    first_paragraph = self._extract_first_paragraph(post.content, max_words=30)
                    prompt = PromptRegistry.render(
                        'AUTO_MEDIA_IMAGE_PROMPT',
                        params={
                            'title': post.title,
                            'category': category_name,
                            'first_paragraph': first_paragraph or 'Контекст отсутствует. Используй основную тему статьи.',
                        },
                        default=(
                            f"изображение в стиле глянцевого журнала для статьи из категории '{category_name}', "
                            f"тематика: {post.title}, яркие цвета, высокое качество, профессиональная фотография"
                            if not first_paragraph else
                            f"Создай изображение в стиле глянцевого журнала для статьи.\n"
                            f"Название статьи: {post.title}\n"
                            f"Сюжет и контекст (первый абзац): {first_paragraph}\n"
                            f"Стиль: глянцевый журнал, яркие цвета, высокое качество, профессиональная фотография\n"
                            f"Категория: {category_name}\n"
                            f"Изображение должно отражать основную тему и настроение статьи."
                        ),
                    )
            
            # Стилевой промпт
            style_prompt = PromptRegistry.render(
                'AUTO_MEDIA_IMAGE_STYLE_PROMPT',
                default="Ты - профессиональный фотограф для модных журналов. Создавай стильные, яркие, качественные изображения."
            )
            
            # Генерируем через GigaChat (async функция - запускаем через asyncio)
            import asyncio
            try:
                # Пытаемся получить существующий loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если loop уже запущен - создаём новый
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                filepath = loop.run_until_complete(gigachat.generate_and_save_image(prompt, style_prompt))
            except RuntimeError:
                # Если нет loop - создаём новый
                filepath = asyncio.run(gigachat.generate_and_save_image(prompt, style_prompt))
            
            if filepath:
                generated_by = self.model
                # Привязываем к посту
                if attach_to_post:
                    post.kartinka = filepath
                    post.save(update_fields=['kartinka'])
                logger.info(f"   ✅ GigaChat сгенерировал изображение ({generated_by}): {filepath}")
                return True, f"Изображение сгенерировано через {generated_by}", filepath
            else:
                return False, "GigaChat не смог сгенерировать изображение", None
        
        except RateLimitCooldown as cooldown:
            logger.warning(f"   ⏸️ GigaChat временно недоступен: {cooldown}")
            return False, str(cooldown), None
        except Exception as e:
            logger.error(f"   ❌ Ошибка генерации через GigaChat: {e}")
            return False, f"Ошибка генерации: {str(e)}", None
    
    def _extract_first_paragraph(self, content: str, max_words: int = 30) -> str:
        """
        Умное извлечение первого абзаца из текста статьи
        
        Args:
            content: HTML контент статьи
            max_words: Максимальное количество слов (по умолчанию 30)
        
        Returns:
            Очищенный текст первого абзаца (до max_words слов)
        """
        if not content:
            return ""
        
        try:
            import re
            from django.utils.html import strip_tags
            
            # ШАГ 1: Удаляем все HTML теги
            clean_text = strip_tags(content)
            
            # ШАГ 2: Удаляем URL ссылки (http://, https://, www.)
            clean_text = re.sub(r'https?://\S+', '', clean_text)
            clean_text = re.sub(r'www\.\S+', '', clean_text)
            
            # ШАГ 3: Удаляем технические элементы
            # Убираем множественные пробелы и переносы строк
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            # ШАГ 4: Извлекаем первый абзац (текст до первой пустой строки или точки с переносом)
            # Разбиваем на предложения
            sentences = re.split(r'[.!?]\s+', clean_text)
            
            # Берем первое предложение + возможно второе, если первое очень короткое
            first_paragraph = ""
            word_count = 0
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                sentence_words = sentence.split()
                
                # Если добавление этого предложения превысит лимит - стоп
                if word_count + len(sentence_words) > max_words:
                    # Добавляем только часть предложения до лимита
                    remaining_words = max_words - word_count
                    if remaining_words > 0:
                        first_paragraph += ' ' + ' '.join(sentence_words[:remaining_words])
                    break
                
                # Добавляем предложение целиком
                if first_paragraph:
                    first_paragraph += '. ' + sentence
                else:
                    first_paragraph = sentence
                
                word_count += len(sentence_words)
                
                # Если набрали достаточно слов - стоп
                if word_count >= max_words:
                    break
            
            # ШАГ 5: Финальная очистка
            first_paragraph = first_paragraph.strip()
            
            # Убираем лишние символы в начале/конце
            first_paragraph = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', first_paragraph)
            
            # ШАГ 6: Ограничиваем длину (на случай если что-то пошло не так)
            words = first_paragraph.split()
            if len(words) > max_words:
                first_paragraph = ' '.join(words[:max_words])
            
            logger.info(f"   📝 Извлечен первый абзац: {len(first_paragraph)} символов, {len(first_paragraph.split())} слов")
            
            return first_paragraph
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка извлечения первого абзаца: {e}")
            return ""
    
    def _try_find_and_download_image(self, post) -> Tuple[bool, str]:
        """
        УМНАЯ СТРАТЕГИЯ поиска изображения с множественными попытками
        """
        logger.info(f"   🔍 Начинаем умный поиск изображения...")
        
        # === СТРАТЕГИЯ 1: Веб-парсинг (Bing, Yandex, Yahoo) ===
        max_web_attempts = 5
        for attempt in range(1, max_web_attempts + 1):
            logger.info(f"   📡 Попытка {attempt}/{max_web_attempts}: Поиск в веб (парсинг)...")
            
            image_url = self._search_web_image(post, attempt)
            
            if image_url:
                success, message = self._download_and_attach_image(post, image_url, attempt)
                if success:
                    return True, message
                else:
                    logger.warning(f"   ⚠️ Не удалось скачать: {message}")
                    # Пробуем следующий источник
                    continue
        
        # === СТРАТЕГИЯ 2: AI Agent поиск через GigaChat ===
        logger.info(f"   🤖 Попытка 4: Запрашиваем URL у AI Agent...")
        ai_image_url = self._ask_ai_for_image_url(post)
        
        if ai_image_url:
            success, message = self._download_and_attach_image(post, ai_image_url, 4)
            if success:
                return True, message
        
        # === СТРАТЕГИЯ 3: Поиск в локальных папках ===
        logger.info(f"   📁 Попытка 5: Поиск в локальных папках...")
        image_path = self._find_local_image(post)
        if image_path:
            return self._attach_local_image(post, image_path)
        
        # === СТРАТЕГИЯ 4: Fallback изображения по категориям ===
        logger.info(f"   🎨 Попытка 6: Используем fallback изображение...")
        fallback_image = self._get_fallback_image(post)
        if fallback_image:
            return self._attach_local_image(post, fallback_image)
        
        return False, "Исчерпаны все стратегии поиска изображения"
    
    def _search_web_image(self, post, attempt: int = 1) -> Optional[str]:
        """Ищет изображение в веб с многоязычными стратегиями"""
        try:
            from .parsers.web_image_parser import get_best_web_image
            
            # Получаем многоязычные запросы
            queries = self._get_multilingual_queries(post, attempt)
            
            # Пробуем каждый запрос
            for query in queries:
                logger.info(f"   🔍 Запрос: '{query}'")
                
                image_url = get_best_web_image(query)
                
                if image_url:
                    logger.info(f"   ✓ Найдено: {image_url[:80]}...")
                    return image_url
            
            # КРАЙНЯЯ МЕРА: Декомпозиция на ключевые слова
            logger.info(f"   🔬 Крайняя мера: декомпозиция на ключевые слова...")
            decomposed_queries = self._decompose_to_keywords(post)
            
            for query in decomposed_queries:
                logger.info(f"   🔍 Корневой запрос: '{query}'")
                
                image_url = get_best_web_image(query)
                
                if image_url:
                    logger.info(f"   ✓ Найдено через декомпозицию: {image_url[:80]}...")
                    return image_url
            
            logger.info(f"   ✗ Не найдено для попытки #{attempt}")
            return None
                
        except Exception as e:
            logger.error(f"   ❌ Ошибка поиска (попытка #{attempt}): {e}")
            return None
    
    def _get_multilingual_queries(self, post, attempt: int) -> list:
        """Генерирует многоязычные поисковые запросы"""
        queries = []
        
        # Базовые русские запросы
        if attempt == 1:
            # Попытка 1: Заголовок + категория
            if hasattr(post, 'category') and post.category:
                queries.append(f"{post.title} {post.category.title}")
            else:
                queries.append(f"{post.title} мода")
        
        elif attempt == 2:
            # Попытка 2: Ключевые слова + фото
            words = post.title.split()[:3]
            query = ' '.join(words)
            if hasattr(post, 'category') and post.category:
                queries.append(f"{query} {post.category.title} фото")
            else:
                queries.append(f"{query} мода фото")
        
        else:
            # Попытка 3: Категория + общие слова
            if hasattr(post, 'category') and post.category:
                queries.append(f"{post.category.title} стиль мода")
            else:
                queries.append("женская мода стиль")
        
        # Добавляем переводы на популярные языки
        try:
            translated_queries = self._translate_queries(queries)
            queries.extend(translated_queries)
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка перевода: {e}")
        
        return queries
    
    def _translate_queries(self, queries: list) -> list:
        """Переводит запросы на популярные языки"""
        try:
            from .gigachat_api import get_gigachat_client
            
            gigachat = get_gigachat_client()
            translated = []
            
            # Языки для перевода (популярные для поиска изображений)
            languages = [
                ("en", "English"),
                ("es", "Spanish"), 
                ("fr", "French"),
                ("de", "German"),
                ("it", "Italian"),
                ("pt", "Portuguese"),
                ("ja", "Japanese"),
                ("ko", "Korean"),
                ("zh", "Chinese"),
                ("ar", "Arabic")
            ]
            
            for query in queries[:2]:  # Переводим только первые 2 запроса
                for lang_code, lang_name in languages:
                    try:
                        prompt = PromptRegistry.render(
                            'AUTO_MEDIA_TRANSLATE_QUERY_PROMPT',
                            params={
                                'query': query,
                                'language_name': lang_name,
                            },
                            default=(
                                f"Переведи этот поисковый запрос на {lang_name} для поиска изображений о моде:\n"
                                f"Запрос: {query}\n"
                                "ТРЕБОВАНИЯ:\n"
                                "- Переведи точно, сохрани смысл\n"
                                "- Добавь слова \"fashion\", \"style\", \"photo\" если нужно\n"
                                "- Верни ТОЛЬКО переведенный запрос\n"
                                "- НЕ добавляй объяснения\n"
                                "Перевод:"
                            ),
                        )
                        
                        response = gigachat.chat(prompt)
                        translated_query = response.strip()
                        
                        if translated_query and len(translated_query) > 3:
                            translated.append(translated_query)
                            logger.info(f"   🌍 {lang_name}: '{translated_query}'")    
                    except Exception as e:
                        logger.warning(f"   ⚠️ Ошибка перевода на {lang_name}: {e}")
                        continue
            
            return translated
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка системы перевода: {e}")
            return []
    
    def _decompose_to_keywords(self, post) -> list:
        """
        КРАЙНЯЯ МЕРА: Декомпозирует запрос на ключевые слова с корнями
        и создает разные комбинации для поиска
        """
        try:
            # Стоп-слова для исключения
            stop_words = {
                'в', 'на', 'и', 'с', 'по', 'для', 'как', 'это', 'или', 'из', 
                'за', 'от', 'к', 'о', 'об', 'про', 'при', 'до', 'под', 'над',
                'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'
            }
            
            # Извлекаем слова из заголовка
            title_words = post.title.lower().split()
            
            # Фильтруем стоп-слова и короткие слова
            keywords = [w for w in title_words if len(w) > 3 and w not in stop_words]
            
            # Находим корни слов (простой стемминг)
            stemmed_keywords = []
            for word in keywords[:5]:  # Берем первые 5 значимых слов
                stem = self._get_word_stem(word)
                stemmed_keywords.append(stem)
            
            # Создаем комбинации из 2-3 слов
            queries = []
            
            # Комбинации из 2 слов
            if len(stemmed_keywords) >= 2:
                from itertools import combinations, permutations
                
                # Все комбинации по 2 слова
                for combo in combinations(stemmed_keywords[:4], 2):
                    queries.append(' '.join(combo))
                    # И в обратном порядке
                    queries.append(' '.join(reversed(combo)))
                
                # Комбинации по 3 слова
                if len(stemmed_keywords) >= 3:
                    for combo in combinations(stemmed_keywords[:4], 3):
                        queries.append(' '.join(combo))
                        # Перестановки первых двух
                        queries.append(f"{combo[1]} {combo[0]} {combo[2]}")
            
            # Добавляем категорию к лучшим комбинациям
            if hasattr(post, 'category') and post.category:
                category_stem = self._get_word_stem(post.category.title.lower())
                
                # Добавляем категорию к первым 3 запросам
                enhanced = []
                for query in queries[:3]:
                    enhanced.append(f"{query} {category_stem}")
                
                queries = enhanced + queries
            
            # Ограничиваем до 10 запросов
            queries = queries[:10]
            
            logger.info(f"   📝 Сгенерировано {len(queries)} корневых комбинаций")
            
            return queries
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка декомпозиции: {e}")
            return []
    
    def _get_word_stem(self, word: str) -> str:
        """
        Простой стемминг для русского и английского языков
        Отсекает типичные окончания
        """
        # Русские окончания
        russian_suffixes = ['ость', 'ение', 'ание', 'ость', 'ние', 'ость', 
                           'ова', 'ева', 'ого', 'его', 'ому', 'ему', 
                           'ым', 'им', 'ых', 'их', 'ой', 'ий', 'ый', 'ая', 'яя', 'ое', 'ее',
                           'ами', 'ями', 'ах', 'ях', 'ов', 'ев', 'ам', 'ям', 'ом', 'ем',
                           'ами', 'ись', 'ось', 'ать', 'ить', 'еть', 'ти', 'чь',
                           'ла', 'ло', 'ли', 'ый', 'ой', 'ая', 'ое', 'ые', 'ие']
        
        # Английские окончания
        english_suffixes = ['ing', 'ed', 'tion', 'sion', 'ness', 'ment', 'ship', 
                           'able', 'ible', 'ful', 'less', 'ous', 'ive', 'al', 'er', 's']
        
        all_suffixes = sorted(russian_suffixes + english_suffixes, key=len, reverse=True)
        
        # Пытаемся отсечь окончание
        for suffix in all_suffixes:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                stem = word[:-len(suffix)]
                # Минимальная длина корня - 3 символа
                if len(stem) >= 3:
                    return stem
        
        # Если не удалось отсечь - возвращаем как есть
        return word
    
    def _find_local_image(self, post) -> Optional[str]:
        """Ищет изображение в локальных папках"""
        try:
            from .image_finder import ImageFinder
            
            finder = ImageFinder()
            
            # Пробуем найти в локальных папках
            keywords = []
            if hasattr(post, 'category') and post.category:
                keywords.append(post.category.title)
            
            logger.info(f"   📁 Поиск в локальных папках media/")
            
            image_url = finder.search_in_local_media(
                keywords=keywords,
                category=post.category.title if hasattr(post, 'category') and post.category else ''
            )
            
            if image_url:
                # Преобразуем URL в путь к файлу
                image_path = image_url.replace(settings.MEDIA_URL, '')
                full_path = os.path.join(settings.MEDIA_ROOT, image_path)
                
                if os.path.exists(full_path):
                    logger.info(f"   ✓ Найдено в локальных папках: {image_path}")
                    return image_path
            
            logger.info(f"   ✗ Не найдено в локальных папках")
            return None
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка поиска в локальных папках: {e}")
            return None
    
    def _download_and_attach_image(self, post, image_url: str, attempt: int = 1) -> Tuple[bool, str]:
        """Скачивает изображение и привязывает к статье с умными таймаутами"""
        try:
            # Увеличиваем таймаут с каждой попыткой
            timeout = 20 + (attempt * 10)  # 30, 40, 50 секунд...
            
            logger.info(f"   ⬇️  Скачивание (таймаут {timeout}с)...")
            
            # Скачиваем изображение с увеличенным таймаутом
            response = self.session.get(image_url, timeout=timeout, stream=True)
            response.raise_for_status()
            
            # Проверяем размер
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.max_file_size:
                return False, f"Изображение слишком большое: {int(content_length) / 1024 / 1024:.1f} MB"
            
            # Читаем содержимое
            image_data = response.content
            
            # Проверяем что это действительно изображение
            try:
                img = Image.open(BytesIO(image_data))
                width, height = img.size
                
                # Проверяем минимальные размеры
                if width < self.min_width or height < self.min_height:
                    return False, f"Изображение слишком маленькое: {width}x{height}"
                
                # Конвертируем в RGB если нужно
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                
                # Сохраняем в формате WebP для экономии места
                output = BytesIO()
                img.save(output, format='WEBP', quality=85)
                image_data = output.getvalue()
                file_extension = 'webp'
                
                logger.info(f"   ✓ Изображение обработано: {width}x{height}, формат WebP")
                
            except Exception as e:
                logger.warning(f"   ⚠️ Не удалось обработать как изображение: {e}")
                # Используем как есть
                file_extension = self._guess_extension(image_url)
            
            # Генерируем уникальное имя файла
            filename = self._generate_unique_filename(post, file_extension)
            
            # Проверяем уникальность изображения
            if not self._is_unique_image(image_data, post):
                return False, "Это изображение уже используется в другой статье"
            
            # Сохраняем файл (путь БЕЗ images/, т.к. upload_to уже добавляет)
            # Привязываем к статье
            post.kartinka.save(filename, ContentFile(image_data), save=False)
            
            logger.info(f"   ✅ Изображение успешно прикреплено: {filename}")
            return True, f"Изображение скачано и прикреплено: {filename}"
            
        except requests.RequestException as e:
            return False, f"Ошибка скачивания: {str(e)}"
        except Exception as e:
            logger.error(f"   ❌ Ошибка обработки изображения: {e}")
            return False, f"Ошибка обработки: {str(e)}"
    
    def _attach_local_image(self, post, image_path: str) -> Tuple[bool, str]:
        """Привязывает локальное изображение к статье"""
        try:
            full_path = os.path.join(settings.MEDIA_ROOT, image_path)
            
            if not os.path.exists(full_path):
                return False, "Локальный файл не найден"
            
            # Читаем файл
            with open(full_path, 'rb') as f:
                image_data = f.read()
            
            # Проверяем уникальность
            if not self._is_unique_image(image_data, post):
                # Если не уникальное, пытаемся найти другое
                logger.warning(f"   ⚠️ Изображение не уникальное, ищем другое...")
                return False, "Изображение не уникальное"
            
            # Привязываем
            post.kartinka = image_path
            
            logger.info(f"   ✅ Локальное изображение прикреплено: {image_path}")
            return True, f"Прикреплено локальное изображение: {image_path}"
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка привязки локального изображения: {e}")
            return False, f"Ошибка: {str(e)}"
    
    def _ask_ai_for_image_url(self, post) -> Optional[str]:
        """Использует AI Agent для поиска прямой ссылки на изображение с многоязычным поиском"""
        try:
            from .gigachat_api import get_gigachat_client
            
            gigachat = get_gigachat_client()
            
            # Пробуем поиск на разных языках
            languages = [
                ("русский", "Russian"),
                ("английский", "English"), 
                ("испанский", "Spanish"),
                ("французский", "French"),
                ("немецкий", "German"),
                ("итальянский", "Italian")
            ]
            
            for lang_name, lang_code in languages:
                try:
                    # Формируем многоязычный запрос к AI
                    prompt = PromptRegistry.render(
                        'AUTO_MEDIA_IMAGE_URL_PROMPT',
                        params={
                            'title': post.title,
                            'category': post.category.title if hasattr(post, 'category') and post.category else 'Мода',
                            'language_name': lang_name,
                        },
                        default=(
                            "Найди ПРЯМУЮ ССЫЛКУ на качественное изображение для статьи о моде.\n"
                            f"Название статьи: {post.title}\n"
                            f"Категория: {post.category.title if hasattr(post, 'category') and post.category else 'Мода'}\n"
                            f"Язык поиска: {lang_name}\n\n"
                            "ТРЕБОВАНИЯ:\n"
                            f"- Ищи изображения на {lang_name} языке\n"
                            "- Верни ТОЛЬКО URL изображения (без объяснений!)\n"
                            "- Изображение должно быть из бесплатных источников (Unsplash, Pexels, Pixabay, Getty Images)\n"
                            "- Формат: https://...jpg или https://...png\n"
                            "- НЕ используй YouTube или защищённые источники\n"
                            "- Добавь ключевые слова: fashion, style, beauty, photo\n\n"
                            "ВЕРНИ ТОЛЬКО URL:"
                        ),
                    )
                    
                    response = gigachat.chat(prompt)
                    
                    # Извлекаем URL из ответа
                    import re
                    urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+\.(?:jpg|jpeg|png|webp)', response, re.IGNORECASE)
                    
                    if urls:
                        image_url = urls[0]
                        logger.info(f"   🤖 AI нашел URL ({lang_name}): {image_url[:80]}...")
                        return image_url
                    else:
                        logger.info(f"   ⚠️ AI не нашел URL на {lang_name}")
                        continue   
                except Exception as e:
                    logger.warning(f"   ⚠️ Ошибка AI поиска на {lang_name}: {e}")
                    continue
            
            logger.info(f"   ⚠️ AI не вернул валидный URL ни на одном языке")
            return None
                
        except Exception as e:
            logger.error(f"   ❌ Ошибка AI поиска: {e}")
            return None
    
    def _get_fallback_image(self, post) -> Optional[str]:
        """Возвращает путь к fallback изображению по категории"""
        try:
            # Маппинг категорий на fallback изображения
            fallback_map = {
                'мода': 'fallback/fashion.webp',
                'красота': 'fallback/beauty.webp',
                'здоровье': 'fallback/health.webp',
                'lifestyle': 'fallback/lifestyle.webp',
                'стиль': 'fallback/style.webp',
            }
            
            # Определяем категорию
            category_key = 'мода'  # по умолчанию
            
            if hasattr(post, 'category') and post.category:
                cat_title_lower = post.category.title.lower()
                
                for key in fallback_map.keys():
                    if key in cat_title_lower:
                        category_key = key
                        break
            
            fallback_path = fallback_map.get(category_key, 'fallback/default.webp')
            full_path = os.path.join(settings.MEDIA_ROOT, fallback_path)
            
            if os.path.exists(full_path):
                logger.info(f"   ✓ Используем fallback: {fallback_path}")
                return fallback_path
            else:
                logger.warning(f"   ⚠️ Fallback не найден: {fallback_path}")
                return None
                
        except Exception as e:
            logger.error(f"   ❌ Ошибка fallback: {e}")
            return None
    
    def _is_unique_image(self, image_data: bytes, current_post) -> bool:
        """Проверяет уникальность изображения через хеш"""
        try:
            # Вычисляем MD5 хеш изображения
            image_hash = hashlib.md5(image_data).hexdigest()
            
            # Проверяем есть ли такой же хеш в других статьях
            from blog.models import Post
            
            # Получаем все опубликованные статьи с изображениями
            other_posts = Post.objects.exclude(pk=current_post.pk if current_post.pk else None)
            other_posts = other_posts.filter(kartinka__isnull=False).exclude(kartinka='')
            
            for other_post in other_posts[:100]:  # Проверяем последние 100
                if other_post.kartinka:
                    try:
                        if hasattr(other_post.kartinka, 'path') and os.path.exists(other_post.kartinka.path):
                            with open(other_post.kartinka.path, 'rb') as f:
                                other_hash = hashlib.md5(f.read()).hexdigest()
                                if other_hash == image_hash:
                                    logger.warning(f"   ⚠️ Дубль найден в статье #{other_post.id}")
                                    return False
                    except:
                        continue
            
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Ошибка проверки уникальности: {e}")
            # В случае ошибки считаем уникальным
            return True
    
    def _generate_unique_filename(self, post, extension: str) -> str:
        """Генерирует уникальное имя файла"""
        # Базовое имя из заголовка
        base_name = slugify(post.title)[:50]
        
        # Добавляем timestamp для уникальности
        import time
        timestamp = int(time.time())
        
        # Добавляем random для полной уникальности
        import random
        random_part = random.randint(1000, 9999)
        
        filename = f"{base_name}_{timestamp}_{random_part}.{extension}"
        
        return filename
    
    def _guess_extension(self, url: str) -> str:
        """Угадывает расширение файла из URL"""
        url_lower = url.lower()
        
        if '.jpg' in url_lower or '.jpeg' in url_lower:
            return 'jpg'
        elif '.png' in url_lower:
            return 'png'
        elif '.webp' in url_lower:
            return 'webp'
        elif '.gif' in url_lower:
            return 'gif'
        else:
            return 'jpg'  # По умолчанию

    # ------------------------- HOROSCOPE PROMPT -----------------------------
    def _build_horoscope_prompt(self, post) -> str:
        """Строгий промпт для гороскопов, если custom_image_prompt не передан."""
        try:
            import re
            # Пытаемся вытащить знак из заголовка: "Гороскоп для Козерог ..."
            m = re.search(r"Гороскоп\s+для\s+([А-ЯЁа-яё]+)", post.title)
            sign = m.group(1) if m else 'знак зодиака'
        except Exception:
            sign = 'знак зодиака'
        # Пытаемся вытащить сезон из текста (если генератор вставил)
        season = 'сезон'  # нейтрально, чтобы не мешать
        try:
            sm = re.search(r"сезон\s+([а-яёA-Za-z]+)", post.content or '')
            if sm:
                season = sm.group(1)
        except Exception:
            pass
        # Итоговый промпт
        prompt = PromptRegistry.render(
            'AUTO_MEDIA_HOROSCOPE_PROMPT',
            params={
                'sign': sign,
                'season': season,
            },
            default=(
                f"Фотореалистичные мужчина и женщина, явно выраженный типаж {sign}, "
                f"модные street style образы, Москва, {season}, полный рост, естественный дневной свет, "
                "fashion editorial, high detail, 8k"
            ),
        )
        logger.info(f"   🎯 Сформирован horoscope prompt: {prompt}")
        return prompt

