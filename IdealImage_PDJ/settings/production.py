"""
Настройки для ПРОДАКШЕНА (DEBUG = False)
Максимальная безопасность, производительность, скрытие ошибок
"""
from .base import *

# DEBUG режим - скрываем ошибки
DEBUG = config('DEBUG', default=False, cast=bool)

# Пути для статики и медиа на VPS
STATIC_ROOT = '/var/www/idealimage/staticfiles'
MEDIA_ROOT = '/var/www/idealimage/media'

# Whitenoise для раздачи статики с компрессией (только в prod)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security настройки для продакшена (включены только если DEBUG=False)
if not DEBUG:
    SECURE_SSL_REDIRECT = True  # Перенаправление на HTTPS
    SECURE_HSTS_SECONDS = 31536000  # 1 год HSTS
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True  # Защита от MIME-sniffing
    SECURE_BROWSER_XSS_FILTER = True  # XSS защита в браузере
    X_FRAME_OPTIONS = 'SAMEORIGIN'  # Защита от clickjacking (SAMEORIGIN для iframe видео)
    CSRF_COOKIE_SECURE = True  # CSRF cookie только через HTTPS
    CSRF_TRUSTED_ORIGINS = [
        'https://idealimage.ru',
        'https://www.idealimage.ru',
    ]  # Доверенные origin для CSRF
    SESSION_COOKIE_SECURE = True  # HTTPS only для сессий

# Дополнительные доверенные origins из переменной окружения (для временных IP)
extra_origins = config('CSRF_TRUSTED_ORIGINS', default='')
if extra_origins:
    CSRF_TRUSTED_ORIGINS.extend(extra_origins.split(','))

# Уровень логирования - только важное в prod
LOGGING['loggers']['django']['level'] = 'WARNING'  # Только предупреждения и ошибки
LOGGING['loggers']['django.request']['level'] = 'ERROR'  # Только ошибки запросов
LOGGING['loggers']['Asistent']['level'] = 'INFO'  # AI логи оставляем INFO

# Sentry для отслеживания ошибок (опционально)
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
        ],
        traces_sample_rate=0.1,  # 10% запросов для tracing
        send_default_pii=False,
    )

