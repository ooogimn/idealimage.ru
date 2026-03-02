#!/bin/bash
# ЭКСТРЕННОЕ ИСПРАВЛЕНИЕ - минимальное использование fork
# Использует только встроенные команды bash

PROJECT_DIR="/home/users/j/j7642490/domains/idealimage.ru"
LOG_FILE="$PROJECT_DIR/logs/fix_fork_emergency.log"

echo "ЭКСТРЕННОЕ ИСПРАВЛЕНИЕ FORK ERROR" > "$LOG_FILE"
echo "Дата: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Создаём папку для логов
mkdir -p "$PROJECT_DIR/logs" 2>/dev/null

# 1. Найти и убить ВСЕ процессы qcluster кроме одного
echo "[1] Поиск процессов qcluster..." | tee -a "$LOG_FILE"

# Используем pgrep напрямую (один fork)
PIDS=$(pgrep -f "python.*qcluster" 2>/dev/null)

if [ -n "$PIDS" ]; then
    # Подсчитываем через встроенные функции bash
    COUNT=0
    FIRST_PID=""
    for pid in $PIDS; do
        if [ -z "$FIRST_PID" ]; then
            FIRST_PID=$pid
        fi
        COUNT=$((COUNT + 1))
    done
    
    echo "Найдено процессов: $COUNT" | tee -a "$LOG_FILE"
    echo "Оставляем PID: $FIRST_PID" | tee -a "$LOG_FILE"
    
    # Убиваем остальные
    for pid in $PIDS; do
        if [ "$pid" != "$FIRST_PID" ]; then
            echo "Убиваем PID: $pid" | tee -a "$LOG_FILE"
            kill -9 "$pid" 2>/dev/null
        fi
    done
else
    echo "Процессов qcluster не найдено" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# 2. Найти и убить ВСЕ процессы monitor_djangoq
echo "[2] Поиск процессов monitor_djangoq..." | tee -a "$LOG_FILE"

MONITOR_PIDS=$(pgrep -f "python.*monitor_djangoq" 2>/dev/null)

if [ -n "$MONITOR_PIDS" ]; then
    COUNT=0
    for pid in $MONITOR_PIDS; do
        COUNT=$((COUNT + 1))
    done
    
    echo "Найдено процессов: $COUNT" | tee -a "$LOG_FILE"
    
    if [ "$COUNT" -gt 1 ]; then
        echo "Убиваем все процессы monitor_djangoq..." | tee -a "$LOG_FILE"
        for pid in $MONITOR_PIDS; do
            echo "Убиваем PID: $pid" | tee -a "$LOG_FILE"
            kill -9 "$pid" 2>/dev/null
        done
    fi
else
    echo "Процессов monitor_djangoq не найдено" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"
echo "Исправление завершено. Проверьте лог: $LOG_FILE" | tee -a "$LOG_FILE"
