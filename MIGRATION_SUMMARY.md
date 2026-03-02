# Сводка миграции IdealImage.ru

## Выполненные задачи

### ✅ Этап 1: Исправление багов (11 проблем)

1. **Секреты в `settings/base.py`** - Убраны реальные значения из `default=`
2. **Сломанные методы в `blog/models.py`** - `get_next_by_publish` → `get_next_by_created`
3. **Опечатка `MTTMeta`** → `MPTTMeta` в `blog/models.py`
4. **`@cache_page` на `post_detail`** - Убран декоратор с POST-обрабатывающей вьюхи
5. **`django_browser_reload`** - Обернут в `if settings.DEBUG:`
6. **`Pisaka.prais`** - Добавлен `null=True`
7. **Дублирующий `page_title`** - Удален дубликат в `PostByCategoryListView`

### ✅ Этап 2: Redis Cache + Sessions

- Установлены пакеты: `redis`, `django-redis`
- Настроен Redis для кэширования (2 базы: default + pages)
- SESSION_ENGINE изменен на `django.contrib.sessions.backends.cache`

### ✅ Этап 3: Миграция Django-Q → Celery

#### Основные изменения

1. **Установлены пакеты:**
   - `celery>=5.3.0`
   - `django-celery-beat>=2.6.0`
   - `django-celery-results>=2.5.1`

2. **Созданы файлы:**
   - `IdealImage_PDJ/celery.py` - конфигурация Celery
   - Обновлен `IdealImage_PDJ/__init__.py` - импорт celery app

3. **Обновлены задачи (`@shared_task`):**
   - `Asistent/tasks.py` - все task-функции
   - `Asistent/schedule/tasks.py` - `run_specific_schedule`, `generate_all_horoscopes`
   - `Asistent/moderations/tasks.py` - `daily_article_regeneration`
   - `Asistent/parsers/tasks.py` - `daily_article_parsing`

4. **Обновлены сигналы:**
   - `Asistent/schedule/signals.py` - синхронизация с `PeriodicTask`
   - `Asistent/signals.py` - синхронизация с `PeriodicTask`

5. **Обновлены вызовы задач:**
   - `Asistent/ai_agent.py` - `_queue_task()` использует `.delay()`
   - `Asistent/moderations/admin.py` - `run_regeneration()`
   - `Asistent/parsers/admin.py` - `run_parsing()`
   - `Asistent/schedule/views.py` - `schedule_run_now()`, `run_all_horoscopes()`
   - `Asistent/schedule/management/commands/generate_horoscopes.py`

6. **Обновлены хелперы:**
   - `Asistent/dashboard_helpers.py` - `get_celery_health()`, `get_system_alerts()`

7. **Обновлено приложение:**
   - `Asistent/apps.py` - автозапуск Celery вместо Django-Q

### ✅ Этап 4: MySQL → PostgreSQL

- Обновлен `DATABASES` в `settings/base.py`
- Добавлен `psycopg2-binary` в requirements.txt
- Убран `PyMySQL` из `IdealImage_PDJ/__init__.py`

### ✅ Этап 5: VPS Deployment конфигурация

#### Созданы файлы

1. **`deploy/idealimage.service`** - systemd сервис для Gunicorn
2. **`deploy/idealimage-celery.service`** - systemd сервис для Celery Worker
3. **`deploy/idealimage-celerybeat.service`** - systemd сервис для Celery Beat
4. **`deploy/nginx-idealimage.conf`** - конфигурация Nginx
5. **`deploy/deploy.sh`** - скрипт автоматического деплоя
6. **`deploy/VPS_SETUP.md`** - подробная инструкция по развёртыванию

#### Обновлены настройки

- `IdealImage_PDJ/settings/production.py` - добавлены `STATIC_ROOT`, `MEDIA_ROOT`, Sentry

## Файлы, требующие внимания при деплое

### Перед первым запуском на VPS

1. **Создать `.env` файл** с настройками для PostgreSQL и Redis
2. **Выполнить миграции:** `python manage.py migrate`
3. **Загрузить данные** (если мигрируете с MySQL): `python manage.py loaddata db_backup.json`
4. **Собрать статику:** `python manage.py collectstatic`
5. **Создать суперпользователя:** `python manage.py createsuperuser`

### Запуск на VPS

```bash
# Активировать сервисы
sudo systemctl enable idealimage idealimage-celery idealimage-celerybeat
sudo systemctl start idealimage idealimage-celery idealimage-celerybeat

# Проверить статус
sudo systemctl status idealimage
sudo systemctl status idealimage-celery
```

### Деплой обновлений

```bash
cd /var/www/idealimage
sudo ./deploy/deploy.sh
```

## Переменные окружения (.env)

```env
# Django
DEBUG=False
SECRET_KEY=your-secret-key

# Database (PostgreSQL)
DB_NAME=idealimage
DB_USER=idealimage_user
DB_PASSWORD=your-password
DB_HOST=localhost
DB_PORT=5432

# Redis
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_PAGES_URL=redis://127.0.0.1:6379/2

# Celery
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=django-db

# Email
EMAIL_HOST=smtp.yandex.ru
EMAIL_PORT=465
EMAIL_HOST_USER=your-email@yandex.ru
EMAIL_HOST_PASSWORD=your-password

# Telegram
BOT_TOKEN=your-bot-token

# GigaChat
GIGACHAT_CLIENT_ID=your-client-id
GIGACHAT_CLIENT_SECRET=your-client-secret

# Sentry (опционально)
SENTRY_DSN=https://xxx@yyy.ingest.sentry.io/zzz
```

## Примечания

- **Django-Q полностью удален** из проекта
- **Все периодические задачи** теперь используют `django-celery-beat`
- **Результаты задач** хранятся в `django_celery_results`
- **На VPS** Celery запускается через systemd, а не автоматически
