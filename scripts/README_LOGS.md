# 📋 ИНСТРУКЦИЯ ПО ПРОВЕРКЕ ЛОГОВ GIGACHAT

## 🎯 ДВА СПОСОБА ПРОСМОТРА ЛОГОВ

---

## СПОСОБ 1: Django Management Команда (РЕКОМЕНДУЕТСЯ)

### Базовое использование:

```bash
cd /path/to/idealimage.ru
source venv/bin/activate  # Если используется virtualenv
python manage.py view_gigachat_logs
```

### Примеры с параметрами:

```bash
# Только ошибки (ERROR и CRITICAL)
python manage.py view_gigachat_logs --level ERROR

# Поиск по тексту "пустой путь"
python manage.py view_gigachat_logs --search "пустой путь"

# Логи за последний час (вместо 24 часов)
python manage.py view_gigachat_logs --hours 1

# Только 20 последних записей
python manage.py view_gigachat_logs --limit 20

# Комбинация параметров
python manage.py view_gigachat_logs --level ERROR --hours 2 --limit 10
```

### Все параметры:

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `--hours` | Сколько часов назад искать | 24 |
| `--level` | Уровень: DEBUG, INFO, WARNING, ERROR, CRITICAL | все |
| `--search` | Поиск по тексту в сообщении | нет |
| `--limit` | Максимум записей | 50 |

---

## СПОСОБ 2: SQL Запросы (ПРЯМОЙ ДОСТУП К БД)

### Подключение к MySQL:

```bash
mysql -u your_username -p your_database_name
```

### Готовые SQL запросы:

Файл `scripts/check_gigachat_logs.sql` содержит 10 готовых запросов.

#### 1. Последние 50 логов GigaChat:
```sql
SELECT 
    timestamp,
    level,
    message
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND message LIKE '%gigachat%'
ORDER BY timestamp DESC
LIMIT 50;
```

#### 2. Только ошибки:
```sql
SELECT 
    timestamp,
    level,
    message
FROM Asistent_systemlog
WHERE 
    timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    AND level IN ('ERROR', 'CRITICAL')
    AND message LIKE '%gigachat%'
ORDER BY timestamp DESC;
```

#### 3. Поиск "пустой путь":
```sql
SELECT 
    timestamp,
    message
FROM Asistent_systemlog
WHERE 
    message LIKE '%пустой путь%'
    OR message LIKE '%вернул пустой%'
ORDER BY timestamp DESC
LIMIT 20;
```

#### 4. Ошибки 429 (Too Many Requests):
```sql
SELECT 
    timestamp,
    message
FROM Asistent_systemlog
WHERE 
    message LIKE '%429%'
    OR message LIKE '%Too Many Requests%'
ORDER BY timestamp DESC;
```

---

## 🔍 ЧТО ИСКАТЬ В ЛОГАХ

### Признаки проблем с генерацией изображений:

1. **"GigaChat вернул пустой путь"** - функция вернула None
2. **"Не удалось сгенерировать изображение"** - все модели исчерпаны
3. **"Таймаут"** или **"TimeoutError"** - превышено время ожидания
4. **"429"** или **"Too Many Requests"** - слишком много запросов
5. **"402"** или **"balance"** - недостаточно баланса
6. **"Нет <img> тега"** - некорректный ответ от API
7. **"Ошибка сохранения"** - проблемы с файловой системой

---

## 📊 ИНТЕРПРЕТАЦИЯ ЛОГОВ

### Нормальная генерация (успех):
```
✅ [INFO] 🎨 Асинхронная генерация изображения: Фотореалистичные...
✅ [INFO] 📋 Задача: image_generation → Приоритет: [GigaChat-Pro, ...]
✅ [INFO] 🔄 Попытка генерации через GigaChat-Pro...
✅ [INFO] 📥 Ответ от GigaChat получен
✅ [INFO] 🆔 UUID изображения: abc123...
✅ [INFO] 📥 Изображение скачано, размер: 250000 байт
✅ [INFO] ✅ Изображение сохранено: images/2024/01/gigachat_...jpg
```

### Проблема - таймаут:
```
⚠️ [WARNING] ⏳ Таймаут 60s при генерации через GigaChat-Pro (попытка 1)
⚠️ [WARNING] ⏳ Таймаут 90s при генерации через GigaChat-Pro (попытка 2)
⚠️ [WARNING] ⏳ Таймаут 120s при генерации через GigaChat-Pro (попытка 3)
⚠️ [WARNING] ⛔ Максимум попыток для GigaChat-Pro исчерпан
❌ [ERROR] ❌ Не удалось сгенерировать изображение ни через одну модель
```

### Проблема - rate limit (429):
```
⚠️ [WARNING] 429 Too Many Requests
⚠️ [WARNING] Активен cooldown 300s перед генерацией изображения
```

---

## 🛠️ РЕШЕНИЕ ПРОБЛЕМ

### 1. Если "пустой путь" из-за таймаута:
- **Причина:** Генерация занимает слишком много времени
- **Решение:** Упростите промпт или увеличьте таймауты в коде

### 2. Если ошибка 429:
- **Причина:** Слишком много запросов к API
- **Решение:** Подождите 5 минут (активен cooldown)

### 3. Если все модели исчерпаны:
- **Причина:** Ни GigaChat-Pro, ни Max, ни Lite не справились
- **Решение:** 
  - Проверьте баланс аккаунта
  - Упростите промпт
  - Проверьте интернет-соединение

### 4. Если "Нет <img> тега":
- **Причина:** API вернул текст вместо изображения
- **Решение:** Промпт не подходит для генерации, измените его

---

## 📞 БЫСТРАЯ ДИАГНОСТИКА

### Шаг 1: Проверьте последние ошибки
```bash
python manage.py view_gigachat_logs --level ERROR --hours 1
```

### Шаг 2: Найдите конкретную проблему
```bash
python manage.py view_gigachat_logs --search "пустой путь"
```

### Шаг 3: Посмотрите полный контекст
```bash
python manage.py view_gigachat_logs --hours 1 --limit 100
```

---

## 💡 ПОЛЕЗНЫЕ КОМАНДЫ

```bash
# Логи за последние 30 минут
python manage.py view_gigachat_logs --hours 0.5

# Только WARNING и выше
python manage.py view_gigachat_logs --level WARNING

# Поиск по части текста
python manage.py view_gigachat_logs --search "generate_and_save"

# Экспорт в файл
python manage.py view_gigachat_logs --hours 24 > logs_export.txt
```

---

## 📧 ДЛЯ ОТПРАВКИ В ПОДДЕРЖКУ

Если нужна помощь, отправьте вывод команды:

```bash
python manage.py view_gigachat_logs --level ERROR --hours 24 > error_report.txt
```

Файл `error_report.txt` будет содержать все ошибки за последние 24 часа.













