"""
Валидатор контента для AI-генерируемых статей
Проверяет уникальность, качество и отсутствие спама
"""
import re
import logging
from typing import Dict, List, Tuple
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


class ContentValidator:
    """Валидатор контента для статей"""
    
    # Запрещённые слова и фразы (спам, нецензурная лексика)
    FORBIDDEN_PATTERNS = [
        r'\b(казино|ставки|1xbet|1хбет|букмекер|прогнозы на спорт)\b',
        r'\b(виагра|сиалис|похудеть за \d+ дней)\b',
        r'\b(заработок без вложений|быстрые деньги)\b',
        r'\b(порно|xxx|adult)\b',
    ]
    
    # Минимальные требования
    MIN_WORD_COUNT = 300
    MIN_UNIQUE_WORDS_RATIO = 0.3  # 30% уникальных слов
    MAX_KEYWORD_DENSITY = 0.1  # Не более 10% повторов ключевого слова
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.score = 0.0
    
    def validate(self, content: str, title: str = "") -> Dict:
        """
        Полная валидация контента
        
        Returns:
            Dict с ключами:
            - is_valid: bool
            - score: float (0-100)
            - errors: List[str]
            - warnings: List[str]
            - details: Dict
        """
        self.errors = []
        self.warnings = []
        self.score = 100.0
        
        # Очищаем от HTML для анализа
        plain_text = strip_tags(content)
        
        # Проверяем длину
        self._check_length(plain_text)
        
        # Проверяем на спам
        self._check_spam(plain_text, title)
        
        # Проверяем уникальность слов
        self._check_word_uniqueness(plain_text)
        
        # Проверяем структуру
        self._check_structure(content)
        
        # Проверяем читаемость
        self._check_readability(plain_text)
        
        # Рассчитываем итоговый score
        self.score = max(0, self.score - (len(self.errors) * 15) - (len(self.warnings) * 5))
        
        return {
            'is_valid': len(self.errors) == 0,
            'score': round(self.score, 1),
            'errors': self.errors,
            'warnings': self.warnings,
            'details': {
                'word_count': len(plain_text.split()),
                'char_count': len(plain_text),
                'error_count': len(self.errors),
                'warning_count': len(self.warnings),
            }
        }
    
    def _check_length(self, text: str):
        """Проверка длины текста"""
        words = text.split()
        word_count = len(words)
        
        if word_count < self.MIN_WORD_COUNT:
            self.errors.append(
                f"Текст слишком короткий: {word_count} слов (минимум {self.MIN_WORD_COUNT})"
            )
        elif word_count < 500:
            self.warnings.append(f"Текст коротковат: {word_count} слов (рекомендуется 500+)")
    
    def _check_spam(self, text: str, title: str = ""):
        """Проверка на спам и запрещённые слова"""
        full_text = f"{title} {text}".lower()
        
        for pattern in self.FORBIDDEN_PATTERNS:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                self.errors.append(f"Обнаружен спам: {matches[0]}")
                logger.warning(f"Spam detected: {matches[0]}")
    
    def _check_word_uniqueness(self, text: str):
        """Проверка уникальности слов"""
        words = re.findall(r'\b[a-zA-Zа-яА-ЯёЁ]+\b', text.lower())
        
        if not words:
            self.errors.append("Не удалось извлечь слова из текста")
            return
        
        unique_words = set(words)
        unique_ratio = len(unique_words) / len(words)
        
        if unique_ratio < self.MIN_UNIQUE_WORDS_RATIO:
            self.warnings.append(
                f"Низкая уникальность слов: {unique_ratio:.1%} "
                f"(рекомендуется {self.MIN_UNIQUE_WORDS_RATIO:.0%}+)"
            )
        
        # Проверяем плотность ключевых слов
        word_counts = {}
        for word in words:
            if len(word) > 3:  # Игнорируем короткие слова
                word_counts[word] = word_counts.get(word, 0) + 1
        
        if word_counts:
            most_common = max(word_counts.items(), key=lambda x: x[1])
            density = most_common[1] / len(words)
            
            if density > self.MAX_KEYWORD_DENSITY:
                self.warnings.append(
                    f"Высокая плотность слова '{most_common[0]}': {density:.1%} "
                    f"(рекомендуется <{self.MAX_KEYWORD_DENSITY:.0%})"
                )
    
    def _check_structure(self, html_content: str):
        """Проверка HTML-структуры"""
        # Проверяем наличие заголовков
        h2_count = len(re.findall(r'<h2[^>]*>', html_content, re.IGNORECASE))
        h3_count = len(re.findall(r'<h3[^>]*>', html_content, re.IGNORECASE))
        
        if h2_count == 0:
            self.warnings.append("Отсутствуют заголовки H2 — текст плохо структурирован")
        
        # Проверяем наличие списков
        has_lists = bool(re.search(r'<(ul|ol)[^>]*>', html_content, re.IGNORECASE))
        if not has_lists:
            self.warnings.append("Рекомендуется добавить списки для лучшей читаемости")
        
        # Проверяем наличие абзацев
        p_count = len(re.findall(r'<p[^>]*>', html_content, re.IGNORECASE))
        if p_count < 3:
            self.warnings.append(f"Мало абзацев ({p_count}) — текст может быть плохо воспринимаем")
    
    def _check_readability(self, text: str):
        """Проверка читаемости текста"""
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return
        
        # Средняя длина предложения
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
        
        if avg_sentence_length > 25:
            self.warnings.append(
                f"Слишком длинные предложения (средняя длина {avg_sentence_length:.0f} слов)"
            )
        
        # Проверяем наличие очень длинных предложений
        long_sentences = sum(1 for s in sentences if len(s.split()) > 40)
        if long_sentences > 2:
            self.warnings.append(f"{long_sentences} очень длинных предложений (>40 слов)")
    
    def quick_check(self, content: str) -> bool:
        """Быстрая проверка без деталей"""
        result = self.validate(content)
        return result['is_valid']


def validate_article(content: str, title: str = "") -> Dict:
    """
    Утилитарная функция для быстрой валидации статьи
    
    Usage:
        result = validate_article(article_content, title)
        if not result['is_valid']:
            print(result['errors'])
    """
    validator = ContentValidator()
    return validator.validate(content, title)
