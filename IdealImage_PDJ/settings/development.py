"""
Настройки для РАЗРАБОТКИ (DEBUG = True)
Включает все инструменты разработки, показывает ошибки, авто-перезагрузку
"""
from .base import *

# DEBUG режим - показываем все ошибки
DEBUG = True

# Добавляем Tailwind CSS и browser reload только в dev
INSTALLED_APPS += [
    'tailwind',
    'theme',
    'django_browser_reload',
]

# Добавляем middleware для авто-перезагрузки только в dev
MIDDLEWARE.insert(3, 'django_browser_reload.middleware.BrowserReloadMiddleware')

INTERNAL_IPS = [
    "127.0.0.1",
    "localhost",
]

# Security настройки для разработки (отключены)
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Отключаем CSRF для локальной разработки (только для тестирования!)
# Это позволяет работать через preview/proxy без ошибок CSRF
CSRF_TRUSTED_ORIGINS = ['http://localhost:8010', 'http://127.0.0.1:8010']

# Разрешаем встраивание в iframe (для предпросмотра в IDE)
X_FRAME_OPTIONS = 'ALLOWALL'

# В dev режиме используем LocMemCache для скорости
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'idealimage-dev-cache',
        'TIMEOUT': 1800,
        'OPTIONS': {
            'MAX_ENTRIES': 5000,
        }
    },
    'pages': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'idealimage-pages-dev-cache',
        'TIMEOUT': 1800,
        'OPTIONS': {
            'MAX_ENTRIES': 2000,
        }
    }
}

# Отключаем кэширование сессий для ускорения в dev
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Дополнительные настройки для ускорения разработки
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'  # Отключаем WhiteNoise для статики в dev

# Уровень логирования - более детальный в dev
LOGGING['loggers']['django']['level'] = 'DEBUG'
LOGGING['loggers']['django.request']['level'] = 'INFO'  # Показываем все запросы в dev

