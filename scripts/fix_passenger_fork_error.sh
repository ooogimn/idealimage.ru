#!/bin/bash
# Скрипт диагностики и исправления ошибки "Cannot fork a new process"
# для проекта idealimage.ru

PROJECT_DIR="/home/users/j/j7642490/domains/idealimage.ru"
LOG_FILE="$PROJECT_DIR/logs/fix_fork_error.log"

echo "=========================================="
echo "ДИАГНОСТИКА ОШИБКИ FORK PROCESS"
echo "=========================================="
echo ""

# Создаём папку для логов если нет
mkdir -p "$PROJECT_DIR/logs"

# Записываем в лог
{
    echo "=========================================="
    echo "$(date): ДИАГНОСТИКА ОШИБКИ FORK PROCESS"
    echo "=========================================="
    echo ""
    
    # 1. Проверка запущенных процессов qcluster
    echo "[1] Проверка процессов qcluster:"
    echo "------------------------------------------"
    QCLUSTER_PIDS=$(ps aux | grep -E "[p]ython.*qcluster" | awk '{print $2}' | grep -v "^$")
    if [ -z "$QCLUSTER_PIDS" ]; then
        QCLUSTER_COUNT=0
    else
        QCLUSTER_COUNT=$(echo "$QCLUSTER_PIDS" | wc -l)
    fi
    echo "Найдено процессов qcluster: $QCLUSTER_COUNT"
    if [ "$QCLUSTER_COUNT" -gt 0 ]; then
        echo "PID процессов:"
        ps aux | grep -E "[p]ython.*qcluster" | awk '{print "  PID:", $2, "| CPU:", $3"% | MEM:", $4"% | CMD:", $11, $12, $13}'
    fi
    echo ""
    
    # 2. Проверка процессов monitor_djangoq
    echo "[2] Проверка процессов monitor_djangoq:"
    echo "------------------------------------------"
    MONITOR_PIDS=$(ps aux | grep -E "[p]ython.*monitor_djangoq" | awk '{print $2}' | grep -v "^$")
    if [ -z "$MONITOR_PIDS" ]; then
        MONITOR_COUNT=0
    else
        MONITOR_COUNT=$(echo "$MONITOR_PIDS" | wc -l)
    fi
    echo "Найдено процессов monitor_djangoq: $MONITOR_COUNT"
    if [ "$MONITOR_COUNT" -gt 0 ]; then
        echo "PID процессов:"
        ps aux | grep -E "[p]ython.*monitor_djangoq" | awk '{print "  PID:", $2, "| CPU:", $3"% | MEM:", $4"% | CMD:", $11, $12, $13}'
    fi
    echo ""
    
    # 3. Общее количество процессов пользователя
    echo "[3] Общее количество процессов пользователя j7642490:"
    echo "------------------------------------------"
    TOTAL_PROCS=$(ps -u j7642490 | wc -l)
    echo "Всего процессов: $TOTAL_PROCS"
    echo ""
    
    # 4. Проверка systemd сервиса
    echo "[4] Проверка systemd сервиса ai_agent.service:"
    echo "------------------------------------------"
    if systemctl list-units --type=service --state=running 2>/dev/null | grep -q "ai_agent.service"; then
        echo "Сервис ai_agent.service ЗАПУЩЕН"
        systemctl status ai_agent.service --no-pager -l 2>/dev/null | head -15 || echo "Не удалось получить статус"
    else
        echo "Сервис ai_agent.service НЕ ЗАПУЩЕН или недоступен"
    fi
    echo ""
    
    # 5. Проверка crontab
    echo "[5] Проверка crontab записей:"
    echo "------------------------------------------"
    crontab -l 2>/dev/null | grep -E "(qcluster|monitor_djangoq)" || echo "Нет записей в crontab"
    echo ""
    
    # 6. Лимиты системы
    echo "[6] Лимиты процессов пользователя:"
    echo "------------------------------------------"
    ulimit -a 2>/dev/null | grep -E "(processes|max user processes)" || echo "Не удалось получить лимиты"
    echo ""
    
    # 7. Исправление: остановка лишних процессов
    echo "[7] ОСТАНОВКА ЛИШНИХ ПРОЦЕССОВ:"
    echo "------------------------------------------"
    
    if [ "$QCLUSTER_COUNT" -gt 1 ]; then
        echo "Найдено $QCLUSTER_COUNT процессов qcluster (должен быть только 1)"
        echo "Останавливаем все кроме первого..."
        
        FIRST_PID=$(echo "$QCLUSTER_PIDS" | head -1)
        OTHER_PIDS=$(echo "$QCLUSTER_PIDS" | tail -n +2)
        
        echo "Оставляем PID: $FIRST_PID"
        for pid in $OTHER_PIDS; do
            if [ -n "$pid" ]; then
                echo "  Останавливаем PID: $pid"
                kill -TERM "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
            fi
        done
        
        sleep 2
        
        # Проверяем результат
        REMAINING_PIDS=$(ps aux | grep -E "[p]ython.*qcluster" | awk '{print $2}' | grep -v "^$")
        if [ -z "$REMAINING_PIDS" ]; then
            REMAINING=0
        else
            REMAINING=$(echo "$REMAINING_PIDS" | wc -l)
        fi
        echo "Осталось процессов qcluster: $REMAINING"
    elif [ "$QCLUSTER_COUNT" -eq 1 ]; then
        echo "OK: Найден только 1 процесс qcluster"
    else
        echo "WARNING: Процессов qcluster не найдено"
    fi
    echo ""
    
    # 8. Остановка зависших monitor_djangoq
    if [ "$MONITOR_COUNT" -gt 3 ]; then
        echo "[8] ОСТАНОВКА ЗАВИСШИХ monitor_djangoq:"
        echo "------------------------------------------"
        echo "Найдено $MONITOR_COUNT процессов monitor_djangoq (слишком много)"
        echo "Останавливаем все..."
        for pid in $MONITOR_PIDS; do
            if [ -n "$pid" ]; then
                echo "  Останавливаем PID: $pid"
                kill -TERM "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
            fi
        done
        echo ""
    fi
    
    # 9. Рекомендации
    echo "[9] РЕКОМЕНДАЦИИ:"
    echo "------------------------------------------"
    echo "1. Проверьте systemd сервис: systemctl status ai_agent.service"
    echo "2. Если сервис работает - отключите crontab для monitor_djangoq"
    echo "3. Если crontab работает - отключите systemd сервис"
    echo "4. НЕ используйте оба способа запуска одновременно!"
    echo "5. Уменьшите workers в Q_CLUSTER с 4 до 2 (уже сделано в settings)"
    echo ""
    
    echo "=========================================="
    echo "ДИАГНОСТИКА ЗАВЕРШЕНА"
    echo "=========================================="
    
} | tee -a "$LOG_FILE"

echo ""
echo "Лог сохранён в: $LOG_FILE"
echo ""
echo "Следующие шаги:"
echo "1. Проверьте вывод выше"
echo "2. Выберите ОДИН способ запуска (systemd ИЛИ crontab)"
echo "3. Перезапустите Passenger: touch $PROJECT_DIR/tmp/restart.txt"
