-- ============================================================================
-- SQL ЗАПРОСЫ ДЛЯ ПРОВЕРКИ ЛОГОВ GIGACHAT
-- ============================================================================

-- 1. ПОСЛЕДНИЕ 50 ЛОГОВ ПО GIGACHAT (ЗА ПОСЛЕДНИЕ 24 ЧАСА)
-- ============================================================================
SELECT 
    timestamp,
    level,
    logger_name,
    module,
    function,
    line,
    LEFT(message, 200) as message_preview
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND (
        message LIKE '%gigachat%'
        OR message LIKE '%GigaChat%'
        OR message LIKE '%изображение%'
        OR message LIKE '%генерация%'
    )
ORDER BY timestamp DESC
LIMIT 50;


-- 2. ТОЛЬКО ОШИБКИ (ERROR И CRITICAL)
-- ============================================================================
SELECT 
    timestamp,
    level,
    message
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND level IN ('ERROR', 'CRITICAL')
    AND (
        message LIKE '%gigachat%'
        OR message LIKE '%изображение%'
        OR message LIKE '%пустой путь%'
    )
ORDER BY timestamp DESC
LIMIT 30;


-- 3. ПОИСК КОНКРЕТНОЙ ОШИБКИ "ПУСТОЙ ПУТЬ"
-- ============================================================================
SELECT 
    timestamp,
    level,
    message,
    module,
    function
FROM Asistent_systemlog
WHERE 
    message LIKE '%пустой путь%'
    OR message LIKE '%вернул пустой%'
ORDER BY timestamp DESC
LIMIT 20;


-- 4. СТАТИСТИКА ПО УРОВНЯМ ЛОГОВ (ЗА ПОСЛЕДНИЕ 24 ЧАСА)
-- ============================================================================
SELECT 
    level,
    COUNT(*) as count
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND (
        message LIKE '%gigachat%'
        OR message LIKE '%изображение%'
    )
GROUP BY level
ORDER BY count DESC;


-- 5. ПОСЛЕДНИЕ ЛОГИ ПО ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ
-- ============================================================================
SELECT 
    timestamp,
    level,
    message
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND (
        message LIKE '%Асинхронная генерация%'
        OR message LIKE '%generate_and_save_image%'
        OR message LIKE '%Изображение сохранено%'
        OR message LIKE '%Не удалось сгенерировать%'
    )
ORDER BY timestamp DESC
LIMIT 30;


-- 6. ПОИСК ОШИБОК 429 (TOO MANY REQUESTS)
-- ============================================================================
SELECT 
    timestamp,
    message
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND (
        message LIKE '%429%'
        OR message LIKE '%Too Many Requests%'
        OR message LIKE '%rate limit%'
    )
ORDER BY timestamp DESC
LIMIT 20;


-- 7. ПОИСК ТАЙМАУТОВ
-- ============================================================================
SELECT 
    timestamp,
    message
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND (
        message LIKE '%Таймаут%'
        OR message LIKE '%timeout%'
        OR message LIKE '%TimeoutError%'
    )
ORDER BY timestamp DESC
LIMIT 20;


-- 8. ПОЛНЫЙ ЛОГ ОДНОЙ ГЕНЕРАЦИИ (ЕСЛИ ЗНАЕТЕ ПРИМЕРНОЕ ВРЕМЯ)
-- Замените '2024-01-15 14:30:00' на ваше время
-- ============================================================================
SELECT 
    timestamp,
    level,
    message,
    function
FROM Asistent_systemlog
WHERE 
    timestamp >= '2024-01-15 14:30:00'
    AND timestamp <= '2024-01-15 14:35:00'
    AND (
        message LIKE '%генерация%'
        OR message LIKE '%GigaChat%'
    )
ORDER BY timestamp ASC;


-- 9. КОЛИЧЕСТВО ОШИБОК ПО ЧАСАМ (ПОСЛЕДНИЕ 24 ЧАСА)
-- ============================================================================
SELECT 
    DATE_FORMAT(timestamp, '%Y-%m-%d %H:00') as hour,
    COUNT(*) as error_count
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND level IN ('ERROR', 'CRITICAL')
    AND message LIKE '%gigachat%'
GROUP BY hour
ORDER BY hour DESC;


-- 10. САМЫЕ ЧАСТЫЕ ОШИБКИ
-- ============================================================================
SELECT 
    LEFT(message, 100) as error_message,
    COUNT(*) as count
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND level IN ('ERROR', 'WARNING')
    AND message LIKE '%gigachat%'
GROUP BY LEFT(message, 100)
ORDER BY count DESC
LIMIT 10;













