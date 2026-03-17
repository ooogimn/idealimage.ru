"""
Базовые настройки Django для IdealImage.ru
Общие настройки для dev и prod
"""
import os
from pathlib import Path
from datetime import timedelta
from decouple import config, Config, RepositoryEnv


# Создайте пути внутри проекта следующим образом: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

_env_file_path = BASE_DIR / '.env'
_file_env_config = None
if _env_file_path.exists():
    try:
        _file_env_config = Config(RepositoryEnv(str(_env_file_path)))
    except Exception:
        _file_env_config = None

# Безопасность - используем переменные окружения
SECRET_KEY = config('SECRET_KEY')  # Обязательно задать в .env!


ALLOWED_HOSTS = [
    'idealimage.ru',
    'www.idealimage.ru',
    'ipv6.idealimage.ru',
    'sitemaps.idealimage.ru',
    'localhost',
    '127.0.0.1',
]

SITE_URL = 'https://idealimage.ru'

# Глобальный флаг для ручного отключения AI-обработки
DISABLE_AI = config('DISABLE_AI', default=False, cast=bool)

# IndexNow / Bing IndexNow keys
INDEXNOW_KEY = config('INDEXNOW_KEY', default='')
BING_INDEXNOW_KEY = config('BING_INDEXNOW_KEY', default='')

# Настройки астрологического контекста для гороскопов
ASTRO_DEFAULT_CITY = config('ASTRO_DEFAULT_CITY', default='Москва')
ASTRO_DEFAULT_LATITUDE = config('ASTRO_DEFAULT_LATITUDE', default=55.7558, cast=float)
ASTRO_DEFAULT_LONGITUDE = config('ASTRO_DEFAULT_LONGITUDE', default=37.6173, cast=float)
ASTRO_DEFAULT_TIMEZONE = config('ASTRO_DEFAULT_TIMEZONE', default='Europe/Moscow')
ASTRO_ASPECT_ORB_DEGREES = config('ASTRO_ASPECT_ORB_DEGREES', default=3.0, cast=float)

# Application definition

INSTALLED_APPS = [
    'ckeditor', 'ckeditor_uploader',
    'jazzmin', 'mptt', 'taggit',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.sitemaps',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'blog.apps.BlogConfig',
    'Visitor.apps.VisitorConfig',
    'Home.apps.HomeConfig',
    'Telega.apps.TelegaConfig',
    'donations.apps.DonationsConfig',
    'Asistent.apps.AsistentConfig',  # AI-Ассистент
    'Asistent.schedule.apps.ScheduleConfig',  # Система расписаний и задач
    'Asistent.moderations.apps.ModerationConfig',  # Модерация контента
    'Asistent.parsers.apps.ParsersConfig',  # Парсинг популярных статей
    'Asistent.ChatBot_AI.apps.ChatBotAIConfig',  # Чат-бот AI
    'Sozseti.apps.SozsetiConfig',  # Интеграция социальных сетей
    'advertising.apps.AdvertisingConfig',  # Система управления рекламой
    'utilits.apps.UtilitsConfig',  # Утилиты проекта
    'django_celery_beat',    # Периодические задачи (замена Django-Q Schedule)
    'django_celery_results',  # Хранение результатов (замена Django-Q Success/Failure)
    # Tailwind CSS (только для dev)
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Раздача статики с компрессией
    'django.contrib.sessions.middleware.SessionMiddleware',
    'IdealImage_PDJ.middleware_consent.ConsentMiddleware',  # Считываем cookie-consent в request
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'Visitor.middleware.SessionRefreshMiddleware',  # Автоматическое продление сессии (после AuthenticationMiddleware!)
    'donations.middleware.SubscriptionMiddleware',  # Проверка подписок
    'donations.middleware.PaidContentMiddleware',   # Проверка платного контента
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'blog.middleware_canonical.CanonicalURLMiddleware',  # Обработка GET-параметров и canonical URLs
    'blog.middleware_404.Smart404Middleware',  # Умная обработка 404 ошибок
    'blog.middleware_lazy_loading.LazyLoadingMiddleware',  # Автоматический lazy loading для изображений
    'IdealImage_PDJ.middleware.MediaMimeTypeMiddleware',  # Правильный Content-Type для WebP и медиа
]

ROOT_URLCONF = 'IdealImage_PDJ.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'Sozseti.context_processors.social_links',  # Ссылки на социальные сети
            ],
            'builtins': ['utilits.templatetags.custom_filters'],  # ← Добавить эту строку
        },
    },
]

WSGI_APPLICATION = 'IdealImage_PDJ.wsgi.application'


# ============================================================================
# БАЗА ДАННЫХ — PostgreSQL only
# ============================================================================
for _pg_env_key in (
    'PGHOST',
    'PGPORT',
    'PGDATABASE',
    'PGUSER',
    'PGPASSWORD',
    'PGSERVICE',
    'PGSERVICEFILE',
    'PGPASSFILE',
    'PGOPTIONS',
    'PGSSLMODE',
    'PGREQUIRESSL',
):
    os.environ.pop(_pg_env_key, None)


def _sanitize_db_value(value, *, default=''):
    """
    Нормализует значения DB-параметров из env:
    - убирает случайные неразрывные пробелы и управляющие символы
    - удаляет обрамляющие кавычки после copy/paste
    """
    if value is None:
        return default

    text = str(value).replace('\u00a0', ' ').strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()

    # Оставляем только печатные ASCII-символы, чтобы исключить
    # скрытые Unicode-байты, которые ломают psycopg2 DSN parsing.
    cleaned = ''.join(ch for ch in text if 32 <= ord(ch) <= 126)
    return cleaned or default


def _db_config_value(key: str, default: str = '') -> str:
    # Для DB настроек приоритет у .env файла, чтобы не зависеть
    # от "залипших" переменных окружения в текущем терминале.
    if _file_env_config is not None:
        try:
            return _file_env_config(key, default=default)
        except Exception:
            pass
    return config(key, default=default)


_pg_name = _sanitize_db_value(_db_config_value('POSTGRES_DB', 'postgres'), default='postgres')
_pg_user = _sanitize_db_value(_db_config_value('POSTGRES_USER', 'postgres'), default='postgres')
_pg_password = _sanitize_db_value(_db_config_value('POSTGRES_PASSWORD', ''))
_pg_host = _sanitize_db_value(_db_config_value('POSTGRES_HOST', '127.0.0.1'), default='127.0.0.1')
_pg_port = _sanitize_db_value(_db_config_value('POSTGRES_PORT', '5432'), default='5432')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _pg_name,
        'USER': _pg_user,
        'PASSWORD': _pg_password,
        'HOST': _pg_host,
        'PORT': _pg_port,
        'OPTIONS': {
            'connect_timeout': config('DB_CONNECT_TIMEOUT', default=30, cast=int),
        },
        'ATOMIC_REQUESTS': False,
        'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=300, cast=int),
    }
}

# Кэширование через Redis (django-redis)
# На VPS: REDIS_URL=redis://127.0.0.1:6379/0
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'IGNORE_EXCEPTIONS': True,  # Не падаем если Redis недоступен
        },
        'TIMEOUT': 3600,  # 1 час
        'KEY_PREFIX': 'idealimage',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'IGNORE_EXCEPTIONS': True,
            'MAX_ENTRIES': 20000,
        }
    },
    # Отдельный кэш для страниц (долгий TTL)
    'pages': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_PAGES_URL', default='redis://127.0.0.1:6379/2'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'IGNORE_EXCEPTIONS': True,
        },
        'TIMEOUT': 1800,  # 30 минут
        'KEY_PREFIX': 'idealimage_pages',
    }
}

# Старый DatabaseCache (отключен из-за проблем с блокировками MySQL)
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
#         'LOCATION': 'django_cache_table',
#         'TIMEOUT': 1800,
#         'OPTIONS': {
#             'MAX_ENTRIES': 5000,
#         }
#     }
# }

# LocMemCache (альтернатива, если нужен кэш в памяти процесса)
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
#         'LOCATION': 'unique-snowflake',
#         'TIMEOUT': 1800,
#         'OPTIONS': {
#             'MAX_ENTRIES': 5000,
#         }
#     }
# }

# Настройки для Redis (если появится в будущем)
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#         'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#         },
#         'TIMEOUT': 300,
#         'KEY_PREFIX': 'idealimage',
#     }
# }

# Сессии через Redis (SESSION_CACHE_ALIAS ссылается на 'default' Redis-кэш)
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Настройки сессий для постоянной авторизации
SESSION_COOKIE_AGE = 31536000  # 1 год в секундах (365 дней)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Сессия не истекает при закрытии браузера
SESSION_SAVE_EVERY_REQUEST = True  # Обновлять время жизни сессии при каждом запросе
SESSION_COOKIE_HTTPONLY = True  # Защита от XSS
SESSION_COOKIE_SAMESITE = 'Lax'  # Защита от CSRF

# Флаг для отключения кэширования при тестировании промтов
# Можно устанавливать через .env: DISABLE_CACHE_FOR_TESTING=True
DISABLE_CACHE_FOR_TESTING = config('DISABLE_CACHE_FOR_TESTING', default=False, cast=bool)

AUTH_PASSWORD_VALIDATORS = [
    # Отключены все валидаторы паролей для упрощения регистрации
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
]


# Русификация и временная зона .
LANGUAGE_CODE = 'ru-RU'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True

# Настройки сообщений
from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'debug',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

# Оптимизированные статические файлы
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # Для collectstatic (не используется на локалке)
STATICFILES_DIRS = ['static']  # Наши файлы - Django берёт отсюда на локалке

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
)

# Whitenoise настройки (storage настраивается в dev/prod)
WHITENOISE_MAX_AGE = 31536000  # 1 год кэширования
WHITENOISE_ALLOW_ALL_ORIGINS = False  # Только с нашего домена

# MEDIA FILES
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'

# Настройки для загрузки больших медиа-файлов (видео)
DATA_UPLOAD_MAX_MEMORY_SIZE = 536870912  # 512 MB (для видео до 50-60 минут)
FILE_UPLOAD_MAX_MEMORY_SIZE = 536870912  # 512 MB

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CKEditor настройки
CKEDITOR_UPLOAD_PATH = "uploads/"
CKEDITOR_IMAGE_BACKEND = 'pillow'

CKEDITOR_CONFIGS = {
    'default': {
        'toolbar': 'full',
        'height': 300,
        'width': 850,
        'forcePasteAsPlainText': True,
        'extraPlugins': ','.join([
            'uploadimage',
            'div',
            'autolink',
            'widget',
            'codesnippet',
            # 'html5video',  # Плагин не установлен, убран из конфигурации
            'autoembed',
            'embedsemantic',
            'autogrow',
            'devtools',
            'exportpdf',
            'lineutils',
            'clipboard',
            'dialog',
            'dialogui',
            'elementspath'
        ]),
    }
}
CKEDITOR_UPLOAD_SLUGIFY_FILENAME = False

# Telegram настройки (из переменных окружения)
BOT_TOKEN = config('BOT_TOKEN', default='')
CHAT_ID1 = config('CHAT_ID1', default='@fizkult_hello_beauty')
CHAT_ID2 = config('CHAT_ID2', default='@eat_love_live')
CHAT_ID3 = config('CHAT_ID3', default='@ideal_image_ru')
CHAT_ID4 = config('CHAT_ID4', default='@the_best_hairstyles')
CHAT_ID5 = config('CHAT_ID5', default='@KOSICHKI_GIRLS')
CHAT_ID6 = config('CHAT_ID6', default='@Fashion_Couture_ru')
CHAT_ID7 = config('CHAT_ID7', default='@posecretulive')
CHAT_ID8 = config('CHAT_ID8', default='@LukInterLab_News')
CHAT_ID9 = config('CHAT_ID9', default='@nlpnlpnlpnlpnlpp')
CHAT_ID10 = config('CHAT_ID10', default='@chtotopropsy')
CHAT_ID11 = config('CHAT_ID11', default='@magicstudyy')
CHAT_ID12 = config('CHAT_ID12', default='@tarolives')
CHAT_ID13 = config('CHAT_ID13', default='@matrizalive')
CHAT_ID14 = config('CHAT_ID14', default='@posecretulive')
CHAT_ID15 = config('CHAT_ID15', default='@Meikapps')
CHAT_ID16 = config('CHAT_ID16', default='@Little_mommys_ru')
CHAT_ID17 = config('CHAT_ID17', default='@LapaBebi')
CHAT_ID18 = config('CHAT_ID18', default='@Lackomca')
ADMIN_ALERT_CHAT_ID = config('ADMIN_ALERT_CHAT_ID', default='')
YOOKASSA_WEBHOOK_SECRET = config('YOOKASSA_WEBHOOK_SECRET', default='')
SBER_WEBHOOK_SECRET = config('SBER_WEBHOOK_SECRET', default='')

api_id = config('API_ID', default='19894195')
api_hash = config('API_HASH', default='')
title = config('TITLE', default='Kosichki_shop')
Short_name = config('SHORT_NAME', default='Kosichki')

TAGGIT_STRIP_UNICODE_WHEN_SLUGIFYING = True

# Email настройки (из переменных окружения)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default='587', cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='idealimage.orel@gmail.com')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')

EMAIL_SERVER = EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
EMAIL_ADMIN = [config('EMAIL_ADMIN', default='idealimage.orel@yandex.ru')]

# APScheduler настройки
APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"

# Jazzmin настройки
JAZZMIN_SETTINGS = {
    "site_title": "IdealImage.ru Admin",
    "site_header": "IdealImage.ru",
    "site_brand": "IdealImage.ru",
    "site_icon": "new/img/favicon/favicon-admin.png",
    "site_logo": "new/img/favicon/favicon-admin-192x192.png",
    "welcome_sign": "Добро пожаловать в панель управления IdealImage.ru",
    "copyright": "IdealImage.ru © 2025",
    "user_avatar": None,
    
    # Верхнее меню
    "topmenu_links": [
        {"name": "🏠 Главная", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "🌐 Сайт", "url": "/", "new_window": True},
        {"name": "📊 Статистика", "url": "admin:index"},
    ],
    
    # Показывать боковую панель
    "show_sidebar": True,
    "navigation_expanded": False,  # Свернуто по умолчанию для чистоты
    
    # Кастомные ссылки в меню
    "custom_links": {
        "blog": [{
            "name": "📝 Все статьи",
            "url": "admin:blog_post_changelist",
            "icon": "fas fa-newspaper",
            "permissions": ["blog.view_post"]
        }],
        "Asistent": [{
            "name": "📋 Календарь заданий",
            "url": "admin:Asistent_taskassignment_changelist",
            "icon": "fas fa-calendar-alt",
        }],
    },
    
    # Порядок приложений в меню
    "order_with_respect_to": [
        "blog",          # Блог
        "Visitor",       # Пользователи
        "Asistent",      # AI-Ассистент
        "donations",     # Донаты
        "Telega",        # Telegram
        "auth",          # Аутентификация
    ],
    
    # Иконки для моделей
    "icons": {
        # === АУТЕНТИФИКАЦИЯ ===
        "auth": "fas fa-shield-alt",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        
        # === БЛОГ ===
        "blog": "fas fa-blog",
        "blog.Post": "fas fa-file-alt",
        "blog.Category": "fas fa-folder",
        "blog.Comment": "fas fa-comments",
        "taggit.Tag": "fas fa-tags",
        
        # === ПОЛЬЗОВАТЕЛИ ===
        "Visitor": "fas fa-user-friends",
        "Visitor.Profile": "fas fa-id-card",
        "Visitor.Role": "fas fa-user-tag",
        "Visitor.RoleApplication": "fas fa-file-signature",
        "Visitor.ActivityLog": "fas fa-history",
        
        # === AI-АССИСТЕНТ ===
        "Asistent": "fas fa-robot",
        "Asistent.ContentTask": "fas fa-tasks",
        "Asistent.TaskAssignment": "fas fa-clipboard-check",
        "schedule.AISchedule": "fas fa-calendar-alt",
        "schedule.AIScheduleRun": "fas fa-history",
        "Asistent.ModerationCriteria": "fas fa-check-circle",
        "Asistent.ModerationLog": "fas fa-clipboard-list",
        "Asistent.AuthorNotification": "fas fa-bell",
        "Asistent.AIConversation": "fas fa-comment-dots",
        "Asistent.AIMessage": "fas fa-comment",
        "Asistent.AITask": "fas fa-cog",
        "Asistent.KnowledgeBase": "fas fa-book",
        
        # === ЧАТ-БОТ (в разделе Asistent) ===
        "Asistent.ChatbotSettings": "fas fa-comments",
        "Asistent.ChatbotFAQ": "fas fa-question-circle",
        "Asistent.ChatMessage": "fas fa-comment-alt",
        
        # === ДОНАТЫ ===
        "donations": "fas fa-hand-holding-usd",
        "donations.Donation": "fas fa-donate",
        "donations.Transaction": "fas fa-money-bill-wave",
        
        # === TELEGRAM ===
        "Telega": "fab fa-telegram",
        "Telega.TelegramPublication": "fas fa-paper-plane",
        
        # === СИСТЕМА ===
        "admin.LogEntry": "fas fa-file",
    },
    
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    
    "related_modal_active": False,
    "custom_js": None,
    "show_ui_builder": False,
    
    # Формат форм
    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {
        "auth.user": "collapsible",
        "auth.group": "vertical_tabs",
        "blog.Post": "horizontal_tabs",
        "Asistent.ContentTask": "horizontal_tabs",
    },
    
    # Скрыть приложения (если нужно)
    "hide_apps": [],
    
    # Скрыть модели
    "hide_models": [],
    
    # Языковой выбор
    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-danger",
    "accent": "accent-danger",
    "navbar": "navbar-danger",
    "no_navbar_border": False,
    "navbar_fixed": False,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": False,
    "sidebar": "sidebar-dark-info",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "slate",
    "dark_mode_theme": None,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}

# Логирование
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'IdealImage_PDJ.logging_handlers.LastLinesFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
            'maxlines': 1000,
            'write_every': 10,
            'encoding': 'utf-8',  # Явно указываем кодировку
        },
        'database': {
            'level': 'INFO',
            'class': 'IdealImage_PDJ.logging_handlers.DatabaseLogHandler',
            'batch_size': 50,
            'flush_interval': 5,
        },
        'qcluster_file': {
            'level': 'INFO',
            'class': 'IdealImage_PDJ.logging_handlers.LastLinesFileHandler',
            'filename': BASE_DIR / 'logs' / 'qcluster.log',
            'formatter': 'simple',
            'maxlines': 1000,
            'write_every': 1,
            'encoding': 'utf-8',  # Явно указываем кодировку
        },
        'qcluster_rotating': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'qcluster.archive.log',
            'when': 'midnight',
            'backupCount': 14,
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'qclean_file': {
            'level': 'INFO',
            'class': 'IdealImage_PDJ.logging_handlers.LastLinesFileHandler',
            'filename': BASE_DIR / 'logs' / 'qclean.log',
            'formatter': 'simple',
            'maxlines': 100,
            'encoding': 'utf-8',  # Явно указываем кодировку
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'file', 'database'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file', 'database'],
            'level': 'INFO',
            'propagate': False,
        },
        'Asistent': {
            'handlers': ['console', 'file', 'database'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'django-q': {
            'handlers': ['qcluster_file', 'qcluster_rotating', 'database'],
            'level': 'INFO',
            'propagate': False,
        },
        # Фильтруем 404 для __reload__/script.js (это нормально для dev)
        'django.request': {
            'handlers': ['console', 'file', 'database'],
            'level': 'WARNING',  # Только WARNING и выше (пропускаем INFO 404)
            'propagate': False,
        },
    },
}

# ============================================================================
# CELERY CONFIGURATION (Redis брокер + django-celery-beat/results)
# Заменяет Django-Q
# ============================================================================

CELERY_BROKER_URL = config('REDIS_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = 'django-db'  # Храним результаты в PostgreSQL через django-celery-results
CELERY_CACHE_BACKEND = 'default'     # Дополнительно кэшируем результаты в Redis
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Europe/Moscow'
CELERY_ENABLE_UTC = True
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 1800        # 30 минут (совпадает с бывшим Q_CLUSTER timeout)
CELERY_TASK_SOFT_TIME_LIMIT = 1500   # 25 минут soft limit
CELERY_WORKER_CONCURRENCY = 2        # Количество воркеров (совпадает с бывшим Q_CLUSTER workers)
CELERY_WORKER_MAX_TASKS_PER_CHILD = 500  # Перезапуск воркера после 500 задач (бывший recycle)
CELERY_BEAT_MAX_LOOP_INTERVAL = 30   # Опрос расписаний каждые 30 секунд
DJANGOQ_QUEUE_ALERT_THRESHOLD = config('DJANGOQ_QUEUE_ALERT_THRESHOLD', default=200, cast=int)
DJANGOQ_STALE_TASK_MINUTES = config('DJANGOQ_STALE_TASK_MINUTES', default=30, cast=int)
PIPELINE_FAILURE_ALERT_THRESHOLD = config('PIPELINE_FAILURE_ALERT_THRESHOLD', default=3, cast=int)
PIPELINE_STALE_RUN_MINUTES = config('PIPELINE_STALE_RUN_MINUTES', default=45, cast=int)
PIPELINE_ALERT_COOLDOWN_MINUTES = config('PIPELINE_ALERT_COOLDOWN_MINUTES', default=60, cast=int)
AISCHEDULE_MAX_ITEMS_PER_HOUR = config('AISCHEDULE_MAX_ITEMS_PER_HOUR', default=30, cast=int)
INTEGRATION_ALERT_COOLDOWN_MINUTES = config('INTEGRATION_ALERT_COOLDOWN_MINUTES', default=30, cast=int)

# ============================================================================
# GIGACHAT API CONFIGURATION
# ============================================================================
# Либо задай только GIGACHAT_API_KEY = готовый Base64 из Sber Studio (Ключ авторизации),
# либо пару: Client_ID (UUID) + GIGACHAT_API_KEY (Client Secret) — код соберёт Base64 сам.
Client_ID = config('Client_ID', default='')
GIGACHAT_API_KEY = config('GIGACHAT_API_KEY', default='')
GIGACHAT_MODEL = config('GIGACHAT_MODEL', default='GigaChat-Max')

# Unsplash API для поиска бесплатных изображений
UNSPLASH_ACCESS_KEY = config('UNSPLASH_ACCESS_KEY', default='')

# ============================================================================
# YANDEX WEBMASTER API CONFIGURATION
# ============================================================================
YANDEX_WEBMASTER_TOKEN = config('YANDEX_WEBMASTER_TOKEN', default='')
YANDEX_WEBMASTER_USER_ID = config('YANDEX_WEBMASTER_USER_ID', default='')
YANDEX_WEBMASTER_HOST_ID = config('YANDEX_WEBMASTER_HOST_ID', default='')

# ============================================================================
# AI-ASSISTANT CONFIGURATION
# ============================================================================
ARTICLE_STATUS_CHOICES = [
    ('draft', 'Черновик'),
    ('on_moderation', 'На модерации'),
    ('published', 'Опубликовано'),
    ('archived', 'Архив'),
]

