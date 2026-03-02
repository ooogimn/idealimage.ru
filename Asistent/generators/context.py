"""
Построитель контекста переменных для UniversalContentGenerator
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from django.utils import timezone

from Asistent.models import PromptTemplate
from Asistent.generators.base import GeneratorMode

logger = logging.getLogger(__name__)

# Константы для автоматического режима
MONTH_NAMES = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
]

WEEKDAY_NAMES = [
    'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'
]

SEASONS = {
    12: 'зима', 1: 'зима', 2: 'зима',
    3: 'весна', 4: 'весна', 5: 'весна',
    6: 'лето', 7: 'лето', 8: 'лето',
    9: 'осень', 10: 'осень', 11: 'осень',
}


class UniversalContextBuilder:
    """
    Построитель контекста переменных для генерации контента.
    Объединяет переменные из шаблона, пользовательские переменные и автоматические.
    """
    
    def __init__(
        self,
        template: PromptTemplate,
        user_variables: Dict[str, Any] = None,
        mode: GeneratorMode = GeneratorMode.AUTO
    ):
        self.template = template
        self.user_variables = user_variables or {}
        self.mode = mode
    
    def build(self, schedule_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Построение полного контекста переменных.
        
        Args:
            schedule_payload: Дополнительные переменные из расписания
        
        Returns:
            Словарь со всеми переменными для подстановки в промпт
        """
        context = {}
        
        # 1. Базовые переменные из шаблона (инициализируем пустыми строками)
        if self.template.variables:
            for var_name in self.template.variables:
                context[var_name] = ""
        
        # 2. Автоматические переменные (определяем ПЕРЕД пользовательскими, чтобы базовые значения были)
        # Для AUTO режима - полный набор переменных
        # Для INTERACTIVE режима - для всех типов статей (включая обычные статьи)
        auto_variables = {}
        if self.mode == GeneratorMode.AUTO:
            auto_variables = self._build_auto_mode_variables(context)
        elif self.mode == GeneratorMode.INTERACTIVE:
            # Для интерактивного режима тоже определяем переменные автоматически
            # Это нужно для правильного заполнения date, year, season, category и т.д.
            auto_variables = self._build_auto_mode_variables(context)
        
        # Обновляем контекст автоматическими переменными
        context.update(auto_variables)
        
        # 3. Пользовательские переменные (могут перезаписать автоматические)
        context.update(self.user_variables)
        
        # 4. Переменные из расписания (приоритет выше всего)
        if schedule_payload:
            context.update(schedule_payload)
            
            # Добавляем категорию из расписания или шаблона
            category_id = schedule_payload.get('category_id')
            if category_id:
                try:
                    from blog.models import Category
                    category = Category.objects.get(id=category_id)
                    context['category'] = category.title
                    logger.debug(f"   📂 Категория из category_id: {category.title}")
                except Category.DoesNotExist:
                    logger.warning(f"   ⚠️ Категория с ID {category_id} не найдена")
            
            # Или из schedule.category напрямую
            category_obj = schedule_payload.get('category')
            if category_obj:
                if hasattr(category_obj, 'title'):
                    context['category'] = category_obj.title
                    logger.debug(f"   📂 Категория из объекта: {category_obj.title}")
                else:
                    context['category'] = str(category_obj)
                    logger.debug(f"   📂 Категория из объекта (строка): {category_obj}")
        
        # Если категория всё ещё не заполнена, пробуем взять из шаблона
        if not context.get('category') and self.template.blog_category:
            context['category'] = self.template.blog_category.title
            logger.debug(f"   📂 Категория из шаблона: {self.template.blog_category.title}")
        
        # Для INTERACTIVE режима также добавляем категорию из шаблона, если она не была добавлена ранее
        if self.mode == GeneratorMode.INTERACTIVE and not context.get('category') and self.template.blog_category:
            context['category'] = self.template.blog_category.title
        
        return context
    
    def _build_auto_mode_variables(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Переменные для автоматического режима.
        
        Args:
            context: Текущий контекст (для проверки уже существующих переменных)
        
        Returns:
            Словарь с переменными для AUTO режима
        """
        variables = {}
        # Используем локальное время (timezone.now() уже учитывает TIME_ZONE из settings)
        now = timezone.now()
        
        # Дата и время
        # Для INTERACTIVE режима используем сегодняшнюю дату (дата написания статьи)
        # Для AUTO режима используем завтра (для гороскопов и планирования)
        if self.mode == GeneratorMode.INTERACTIVE:
            target_date_offset = 0  # Сегодня для тестирования
        else:
            target_date_offset = context.get('target_date_offset', 1)
            # Убеждаемся, что offset >= 1 для "завтра"
            if target_date_offset < 1:
                target_date_offset = 1
        target_date = now + timedelta(days=target_date_offset)
        
        # Форматированная дата
        formatted_date = f"{target_date.day} {MONTH_NAMES[target_date.month - 1]} {target_date.year}"
        formatted_today = f"{now.day} {MONTH_NAMES[now.month - 1]} {now.year}"
        
        variables['date'] = formatted_date
        variables['next_date'] = formatted_date
        variables['current_date'] = formatted_today  # Сегодня
        
        # День недели
        weekday = WEEKDAY_NAMES[target_date.weekday()]
        variables['weekday'] = weekday
        
        # Выходной/рабочий день
        is_weekend = target_date.weekday() >= 5
        variables['weekend_status'] = 'выходной день' if is_weekend else 'рабочий день'
        
        # Время года
        season = SEASONS[target_date.month]
        variables['season'] = season
        
        # Год (всегда текущий год, независимо от target_date)
        variables['year'] = now.year
        variables['current_year'] = now.year
        
        # Ротация знаков зодиака (если это гороскоп)
        # НОВОЕ: Проверяем, не передан ли знак уже явно
        zodiac_sign = None
        if self.template.category == 'horoscope' and 'zodiac_sign' not in context:
            zodiac_sign = self._get_next_zodiac_from_rotation()
            variables['zodiac_sign'] = zodiac_sign
            variables['zodiac'] = zodiac_sign  # Альтернативное имя
            logger.info(f"   ♈ Автоматический выбор знака: {zodiac_sign}")
        elif 'zodiac_sign' in context:
            # Используем знак из расписания
            zodiac_sign = context['zodiac_sign']
            variables['zodiac_sign'] = zodiac_sign
            variables['zodiac'] = zodiac_sign
            logger.info(f"   ♈ Использован знак из расписания: {zodiac_sign}")
        
        # Для гороскопов добавляем астрологические данные
        if self.template.category == 'horoscope' and zodiac_sign:
            astro_variables = self._build_astrological_variables(zodiac_sign)
            variables.update(astro_variables)
        
        return variables
    
    def _build_astrological_variables(self, zodiac_sign: str) -> Dict[str, Any]:
        """
        Построение астрологических переменных для гороскопов.
        Использует AstrologyContextBuilder для получения эфемерид.
        
        Args:
            zodiac_sign: Знак зодиака
        
        Returns:
            Словарь с астрологическими переменными
        """
        try:
            from Asistent.services.astro_context import AstrologyContextBuilder
            
            builder = AstrologyContextBuilder()
            astro_context = builder.build_context(zodiac_sign)
            
            # Преобразуем в формат, который ожидает промпт
            variables = {
                'current_date': astro_context.get('current_date', ''),
                'next_date': astro_context.get('next_date', ''),
                'weekday': astro_context.get('weekday', ''),
                'weekend_status': astro_context.get('weekend_status', ''),
                'season': astro_context.get('season', ''),
                'weather': astro_context.get('weather', ''),
                'sun_sign': astro_context.get('sun_sign', ''),
                'sun_degrees': astro_context.get('sun_degrees', ''),
                'moon_sign': astro_context.get('moon_sign', ''),
                'moon_degrees': astro_context.get('moon_degrees', ''),
                'moon_phase': astro_context.get('moon_phase', ''),
                'mercury_sign': astro_context.get('mercury_sign', ''),
                'venus_sign': astro_context.get('venus_sign', ''),
                'mars_sign': astro_context.get('mars_sign', ''),
                'aspects': astro_context.get('aspects', ''),
                'ascendant': astro_context.get('ascendant', ''),
                'planets_in_houses_text': astro_context.get('planets_in_houses_text', ''),
            }
            
            logger.info(f"   🌟 Астрологические данные получены для {zodiac_sign}")
            logger.debug(f"   📊 Переменные: current_date={variables.get('current_date')}, next_date={variables.get('next_date')}, weekday={variables.get('weekday')}, season={variables.get('season')}")
            return variables
            
        except Exception as e:
            logger.warning(f"   ⚠️ Не удалось получить астрологические данные: {e}", exc_info=True)
            # Возвращаем пустые значения, чтобы не ломать генерацию
            return {
                'weather': 'Данные о погоде недоступны',
                'sun_sign': '',
                'sun_degrees': '',
                'moon_sign': '',
                'moon_degrees': '',
                'moon_phase': '',
                'mercury_sign': '',
                'venus_sign': '',
                'mars_sign': '',
                'aspects': 'Данные об аспектах недоступны',
                'ascendant': '',
                'planets_in_houses_text': '',
            }
    
    def _get_next_zodiac_from_rotation(self) -> str:
        """
        Получить следующий знак зодиака из ротации.
        Простая реализация - можно улучшить с сохранением состояния.
        """
        zodiac_signs = [
            'Овен', 'Телец', 'Близнецы', 'Рак',
            'Лев', 'Дева', 'Весы', 'Скорпион',
            'Стрелец', 'Козерог', 'Водолей', 'Рыбы'
        ]
        
        # Простая ротация на основе дня месяца
        day_of_month = timezone.now().day
        index = (day_of_month - 1) % len(zodiac_signs)
        
        return zodiac_signs[index]

