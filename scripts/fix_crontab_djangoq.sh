#!/bin/bash
# Скрипт автоматического исправления crontab для мониторинга Django-Q

PROJECT_DIR="/home/users/j/j7642490/domains/idealimage.ru"
PYTHON_BIN="$PROJECT_DIR/.venv/python311/bin/python"
LOG_FILE="$PROJECT_DIR/logs/djangoq_monitor.log"

echo "=========================================="
echo "ИСПРАВЛЕНИЕ CRONTAB ДЛЯ DJANGO-Q"
echo "=========================================="
echo ""

# Создаём временный файл
TEMP_CRON=$(mktemp)

# Получаем текущий crontab
crontab -l > "$TEMP_CRON" 2>/dev/null || echo "" > "$TEMP_CRON"

echo "[1] Удаление старых записей Django-Q..."

# Удаляем все старые записи связанные с qcluster
sed -i '/check_qcluster\.sh/d' "$TEMP_CRON"
sed -i '/pgrep.*qcluster/d' "$TEMP_CRON"
sed -i '/python.*qcluster.*>>.*logs\/qcluster\.log/d' "$TEMP_CRON"
sed -i '/monitor_djangoq/d' "$TEMP_CRON"

echo "[2] Добавление правильной записи monitor_djangoq..."

# Создаём новый crontab
{
    # Добавляем комментарий
    echo "# Django-Q: умная проверка и автоперезапуск каждые 5 минут"
    
    # Добавляем новую строку
    echo "*/5 * * * * cd $PROJECT_DIR && $PYTHON_BIN manage.py monitor_djangoq >> $LOG_FILE 2>&1"
    echo ""
    
    # Добавляем остальные существующие записи (monitor_gigachat, qclean)
    grep -E "(monitor_gigachat|qclean)" "$TEMP_CRON" || true
    
} > "${TEMP_CRON}.new"

# Устанавливаем новый crontab
crontab "${TEMP_CRON}.new"

# Проверяем результат
if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "[OK] CRONTAB УСПЕШНО ОБНОВЛЕН!"
    echo "=========================================="
    echo ""
    echo "Текущий crontab:"
    echo "------------------------------------------"
    crontab -l
    echo "------------------------------------------"
    echo ""
    echo "Проверка логов через 5 минут:"
    echo "  tail -f $LOG_FILE"
else
    echo ""
    echo "[ERROR] ОШИБКА при обновлении crontab!"
    exit 1
fi

# Удаляем временные файлы
rm -f "$TEMP_CRON" "${TEMP_CRON}.new"

echo ""
echo "Готово! Мониторинг Django-Q будет работать каждые 5 минут."
