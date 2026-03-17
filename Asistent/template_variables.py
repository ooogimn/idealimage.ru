"""
Извлечение динамических переменных из текста промпт-шаблонов.

Поддерживается синтаксис:
- Python format: {variable}, {zodiac_sign}, {date}
- Двойные фигурные скобки (Jinja2-стиль): {{ variable }} — извлекается имя без пробелов

Используется для дашборда: показ полей подстановки в форме расписания по выбранному шаблону.
"""
import re
from typing import List, Optional

# Python .format(): {name} или {name:...} или {name!r}
# Захватываем только имя переменной (до : или ! или })
RE_BRACE_SINGLE = re.compile(r'\{([a-zA-Z_][a-zA-Z0-9_]*)(?:\![rsa]|[:\.].*?)?\}')
# Jinja2-стиль: {{ name }} или {{name}}
RE_BRACE_DOUBLE = re.compile(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}')


def extract_template_variables(text: Optional[str]) -> List[str]:
    """
    Извлекает уникальный список имён переменных из строки.

    Поддерживаются шаблоны: {var}, {var:format}, {{ var }}.

    Args:
        text: Строка шаблона (промпт, критерии и т.д.)

    Returns:
        Отсортированный список уникальных имён переменных.
    """
    if not text or not isinstance(text, str):
        return []
    seen = set()
    for pattern in (RE_BRACE_SINGLE, RE_BRACE_DOUBLE):
        for m in pattern.finditer(text):
            seen.add(m.group(1))
    return sorted(seen)


def extract_from_template_fields(
    template_text: Optional[str] = None,
    title_criteria: Optional[str] = None,
    image_search_criteria: Optional[str] = None,
    image_generation_criteria: Optional[str] = None,
    tags_criteria: Optional[str] = None,
    debug_script: Optional[str] = None,
) -> List[str]:
    """
    Собирает все переменные из полей шаблона промпта.

    Args:
        template_text: Основной шаблон промпта
        title_criteria: Критерии заголовка
        image_search_criteria: Критерии поиска изображения
        image_generation_criteria: Критерии генерации изображения
        tags_criteria: Критерии тегов
        debug_script: Скрипт отладки

    Returns:
        Отсортированный список уникальных имён переменных.
    """
    all_vars = []
    for field in (
        template_text,
        title_criteria,
        image_search_criteria,
        image_generation_criteria,
        tags_criteria,
        debug_script,
    ):
        all_vars.extend(extract_template_variables(field))
    return sorted(set(all_vars))
