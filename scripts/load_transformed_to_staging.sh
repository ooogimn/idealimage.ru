#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# load_transformed_to_staging.sh
# Загружает трансформированный дамп в staging PostgreSQL
# Запуск: ./load_transformed_to_staging.sh transformed.sql
# =============================================================================

DUMP_FILE="${1:-transformed.sql}"
COMPOSE_FILE="docker-compose.staging.yml"
PG_DB="${STAGING_POSTGRES_DB:-idealimage}"
PG_USER="${STAGING_POSTGRES_USER:-ideal}"

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "Ошибка: файл $DUMP_FILE не найден"
  exit 1
fi

if ! docker compose -f "$COMPOSE_FILE" ps postgres &>/dev/null; then
  echo "PostgreSQL-контейнер не запущен. Запускаю docker-compose..."
  docker compose -f "$COMPOSE_FILE" up -d postgres
  sleep 8
fi

echo "→ Загружаю $DUMP_FILE в staging PostgreSQL..."
echo "→ Очищаю public schema (staging reset)..."

docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
  -U "$PG_USER" \
  -d "$PG_DB" \
  -v ON_ERROR_STOP=1 \
  --no-psqlrc \
  -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"

cat "$DUMP_FILE" | docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
  -U "$PG_USER" \
  -d "$PG_DB" \
  -v ON_ERROR_STOP=1 \
  --echo-all \
  --single-transaction \
  --no-psqlrc

echo
echo "✓ Загрузка завершена"
echo "Проверь статус:"
echo "  docker compose -f $COMPOSE_FILE logs postgres | tail -n 30"
echo
echo "Следующий шаг: запустить smoke-проверки"
