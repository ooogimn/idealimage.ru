# Инструкция по развёртыванию IdealImage.ru на VPS

## Требования к серверу

- Ubuntu 22.04 LTS (рекомендуется)
- 2+ CPU cores
- 4+ GB RAM
- 50+ GB SSD

## 1. Подготовка сервера

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка необходимых пакетов
sudo apt install -y python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib redis-server nginx \
    git curl wget certbot python3-certbot-nginx \
    build-essential libpq-dev

# Создание пользователя для приложения
sudo useradd -r -s /bin/false www-data 2>/dev/null || true
```

## 2. Настройка PostgreSQL

```bash
# Запуск PostgreSQL
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Создание базы данных и пользователя
sudo -u postgres psql <<EOF
CREATE DATABASE idealimage;
CREATE USER idealimage_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE idealimage TO idealimage_user;
\q
EOF
```

## 3. Настройка Redis

```bash
# Redis уже установлен и запущен
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Проверка
redis-cli ping  # должно вернуть PONG
```

## 4. Настройка проекта

```bash
# Создание директории
sudo mkdir -p /var/www/idealimage
sudo chown -R $USER:$USER /var/www/idealimage

# Клонирование проекта (или загрузка архива)
cd /var/www/idealimage
git clone https://your-repo/idealimage.git . || echo "Копируйте файлы вручную"

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Создание директорий
mkdir -p /var/www/idealimage/staticfiles
mkdir -p /var/www/idealimage/media
mkdir -p /var/log/idealimage

# Настройка .env файла
cp .env.example .env
nano .env  # Отредактируйте настройки
```

### Пример .env файла

```env
DEBUG=False
SECRET_KEY=your-very-secure-secret-key-here

# Database (PostgreSQL)
DB_NAME=idealimage
DB_USER=idealimage_user
DB_PASSWORD=your_secure_password
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
EMAIL_HOST_PASSWORD=your-email-password

# Telegram
BOT_TOKEN=your-telegram-bot-token

# GigaChat
GIGACHAT_CLIENT_ID=your-client-id
GIGACHAT_CLIENT_SECRET=your-client-secret

# Sentry (опционально)
SENTRY_DSN=https://xxx@yyy.ingest.sentry.io/zzz
```

## 5. Миграция данных из MySQL (если нужно)

На старом сервере:

```bash
# Дамп данных
python manage.py dumpdata --natural-foreign --natural-primary \
    --exclude=contenttypes --exclude=auth.permission \
    --exclude=django_q.success --exclude=django_q.failure \
    --exclude=django_q.schedule --exclude=django_q.ormq \
    > db_backup.json
```

На новом сервере:

```bash
# Применение миграций
python manage.py migrate

# Загрузка данных
python manage.py loaddata db_backup.json
```

## 6. Настройка systemd сервисов

```bash
# Копирование сервис-файлов
sudo cp deploy/idealimage.service /etc/systemd/system/
sudo cp deploy/idealimage-celery.service /etc/systemd/system/
sudo cp deploy/idealimage-celerybeat.service /etc/systemd/system/

# Создание директории для логов
sudo mkdir -p /var/log/idealimage
sudo chown -R www-data:www-data /var/log/idealimage

# Перезагрузка systemd
sudo systemctl daemon-reload

# Запуск сервисов
sudo systemctl enable idealimage
sudo systemctl enable idealimage-celery
sudo systemctl enable idealimage-celerybeat

sudo systemctl start idealimage
sudo systemctl start idealimage-celery
sudo systemctl start idealimage-celerybeat
```

## 7. Настройка Nginx

```bash
# Копирование конфигурации
sudo cp deploy/nginx-idealimage.conf /etc/nginx/sites-available/idealimage

# Активация сайта
sudo ln -sf /etc/nginx/sites-available/idealimage /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Проверка конфигурации
sudo nginx -t

# Перезапуск Nginx
sudo systemctl restart nginx
```

## 8. SSL сертификат (Let's Encrypt)

```bash
# Получение сертификата
sudo certbot --nginx -d idealimage.ru -d www.idealimage.ru

# Автообновление
sudo systemctl enable certbot.timer
```

## 9. Проверка работоспособности

```bash
# Проверка статуса сервисов
sudo systemctl status idealimage
sudo systemctl status idealimage-celery
sudo systemctl status idealimage-celerybeat
sudo systemctl status nginx
sudo systemctl status redis-server
sudo systemctl status postgresql

# Проверка сайта
curl -I https://idealimage.ru

# Проверка логов
sudo tail -f /var/log/idealimage/error.log
sudo tail -f /var/log/idealimage/celery-worker.log
```

## 10. Деплой обновлений

```bash
# Используйте скрипт деплоя
cd /var/www/idealimage
sudo ./deploy/deploy.sh
```

## Полезные команды

```bash
# Перезапуск всех сервисов
sudo systemctl restart idealimage idealimage-celery idealimage-celerybeat

# Просмотр логов
sudo journalctl -u idealimage -f
sudo journalctl -u idealimage-celery -f

# Очистка кэша Redis
redis-cli FLUSHDB

# Бэкап базы данных
sudo -u postgres pg_dump idealimage > backup_$(date +%Y%m%d).sql

# Восстановление базы данных
sudo -u postgres psql idealimage < backup_YYYYMMDD.sql
```

## Устранение неполадок

### Gunicorn не запускается

```bash
# Проверка прав на сокет
sudo chown www-data:www-data /run/idealimage.sock
sudo chmod 666 /run/idealimage.sock

# Проверка логов
sudo cat /var/log/idealimage/error.log
```

### Celery не подключается к Redis

```bash
# Проверка Redis
redis-cli ping

# Перезапуск Redis
sudo systemctl restart redis-server
```

### Ошибки базы данных

```bash
# Проверка подключения
sudo -u postgres psql -c "\l"

# Проверка прав пользователя
sudo -u postgres psql -c "\du"
```
