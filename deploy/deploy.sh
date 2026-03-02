#!/bin/bash
# Скрипт деплоя IdealImage.ru на VPS
# Запускать из директории /var/www/idealimage

set -e  # Остановка при ошибке

echo "=========================================="
echo "🚀 Деплой IdealImage.ru"
echo "=========================================="
echo ""

# Проверка, что мы в правильной директории
if [ ! -f "manage.py" ]; then
    echo "❌ Ошибка: manage.py не найден. Запустите из корня проекта."
    exit 1
fi

# Активация виртуального окружения
echo "📦 Активация виртуального окружения..."
source venv/bin/activate

# Обновление кода из git (если есть доступ)
if [ -d ".git" ]; then
    echo "📥 Обновление кода из git..."
    git pull origin main || echo "⚠️ Не удалось обновить из git"
fi

# Установка зависимостей
echo "📦 Установка зависимостей..."
pip install -r requirements.txt --quiet

# Миграции базы данных
echo "🗄️  Применение миграций..."
python manage.py migrate --noinput

# Сбор статики
echo "📁 Сбор статических файлов..."
python manage.py collectstatic --noinput --clear

# Компиляция сообщений (если есть переводы)
if [ -d "locale" ]; then
    echo "🌐 Компиляция переводов..."
    python manage.py compilemessages || echo "⚠️ Не удалось скомпилировать переводы"
fi

# Проверка прав на директории
echo "🔐 Настройка прав..."
sudo chown -R www-data:www-data /var/www/idealimage/media/
sudo chown -R www-data:www-data /var/www/idealimage/staticfiles/
sudo chmod -R 755 /var/www/idealimage/media/
sudo chmod -R 755 /var/www/idealimage/staticfiles/

# Перезапуск сервисов
echo "🔄 Перезапуск сервисов..."
sudo systemctl restart idealimage
sudo systemctl restart idealimage-celery
sudo systemctl restart idealimage-celerybeat

# Проверка статуса
echo ""
echo "📊 Статус сервисов:"
sudo systemctl is-active idealimage || echo "⚠️ Gunicorn не запущен"
sudo systemctl is-active idealimage-celery || echo "⚠️ Celery Worker не запущен"
sudo systemctl is-active idealimage-celerybeat || echo "⚠️ Celery Beat не запущен"

echo ""
echo "=========================================="
echo "✅ Деплой завершён!"
echo "=========================================="
echo ""
echo "Проверка работоспособности:"
echo "  curl -I https://idealimage.ru"
echo ""
echo "Логи:"
echo "  sudo tail -f /var/log/idealimage/error.log"
echo "  sudo tail -f /var/log/idealimage/celery-worker.log"
echo ""
