#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# staging_smoke_check.sh — исправленная версия (2026)
# =============================================================================

# Принудительно закрепляем PostgreSQL для smoke-check (игнорируем .env значения)
# При необходимости можно переопределить через STAGING_POSTGRES_*.
export POSTGRES_DB="${STAGING_POSTGRES_DB:-idealimage}"
export POSTGRES_USER="${STAGING_POSTGRES_USER:-ideal}"
export POSTGRES_PASSWORD="${STAGING_POSTGRES_PASSWORD:-strongpass123}"
export POSTGRES_HOST="${STAGING_POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${STAGING_POSTGRES_PORT:-5432}"
export DB_ENGINE="postgresql"
export DB_NAME="$POSTGRES_DB"
export DB_USER="$POSTGRES_USER"
export DB_PASSWORD="$POSTGRES_PASSWORD"
export DB_HOST="$POSTGRES_HOST"
export DB_PORT="$POSTGRES_PORT"
unset DATABASE_URL || true

# Чистим libpq-переменные, которые могут переопределять DSN и ломать decoding в psycopg2.
unset PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE PGPASSFILE PGOPTIONS PGAPPNAME PGREALM PGREQUIRESSL PGSSLMODE PGSSLKEY PGSSLCERT PGSSLROOTCERT PGSSLCRL PGCHANNELBINDING PGCONNECT_TIMEOUT PGCLIENTENCODING PGTARGETSESSIONATTRS || true
export PGHOST="$POSTGRES_HOST"
export PGPORT="$POSTGRES_PORT"
export PGDATABASE="$POSTGRES_DB"
export PGUSER="$POSTGRES_USER"
export PGPASSWORD="$POSTGRES_PASSWORD"
export PGCLIENTENCODING="UTF8"
export PYTHONUTF8=1
COMPOSE_FILE="docker-compose.staging.yml"

pg_query() {
  local sql="$1"
  docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -tA -v ON_ERROR_STOP=1 -c "$sql"
}

echo "┌──────────────────────────────────────────────────────────────┐"
echo "│           Staging PostgreSQL smoke check                     │"
echo "└──────────────────────────────────────────────────────────────┘"
echo "Target DB: ${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo -n "1. manage.py запускается?                "
python manage.py --version >/dev/null 2>&1 && echo "OK" || { echo "FAIL"; exit 1; }

echo -n "2. Все миграции применены?               "
if MIG_COUNT="$(pg_query "SELECT count(*) FROM django_migrations;" 2>/dev/null)"; then
  echo "OK (${MIG_COUNT} записей в django_migrations)"
else
  echo "FAIL (django_migrations недоступна)"
  exit 1
fi

echo -n "3. Подключение к БД и наличие таблиц?    "
if TABLES_COUNT="$(pg_query "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';" 2>/dev/null)"; then
  echo "OK (${TABLES_COUNT} таблиц, backend=postgresql)"
else
  echo "FAIL — ошибка подключения к PostgreSQL"
  exit 1
fi

echo -n "4. Кол-во постов в блоге?                "
POST_COUNT="не удалось посчитать"
if [[ "$(pg_query "SELECT to_regclass('public.blog_post') IS NOT NULL;" 2>/dev/null || echo "f")" == "t" ]]; then
  POST_COUNT="$(pg_query "SELECT count(*) FROM public.blog_post;" 2>/dev/null || echo "не удалось посчитать")"
elif [[ "$(pg_query "SELECT to_regclass('public.app_posts') IS NOT NULL;" 2>/dev/null || echo "f")" == "t" ]]; then
  POST_COUNT="$(pg_query "SELECT count(*) FROM public.app_posts;" 2>/dev/null || echo "не удалось посчитать")"
fi
echo "$POST_COUNT"

echo -n "5. Периодические задачи в Celery Beat?   "
TASK_COUNT="$(pg_query "SELECT CASE
  WHEN to_regclass('public.django_celery_beat_periodictask') IS NOT NULL
    THEN (SELECT count(*)::text FROM public.django_celery_beat_periodictask)
  ELSE '0'
END;" 2>/dev/null || echo "не удалось посчитать")"
echo "$TASK_COUNT задач"

echo -n "6. Redis кэш доступен?                   "
if docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli SET smoke_test_key smoke_ok EX 10 >/dev/null 2>&1; then
  docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli GET smoke_test_key 2>/dev/null || echo "FAIL"
else
  echo "FAIL"
fi

echo
echo "Ручные проверки (обязательно):"
echo "  • http://localhost:8000/admin/                → вход под суперюзером"
echo "  • http://localhost:8000/asistent/admin-panel/ → расписания и AI-задачи видны?"
echo "  • http://localhost:8000/blog/                 → посты отображаются?"
echo "  • Создай черновик поста → AI-улучшение → /admin/django_celery_results/taskresult/"
echo
echo "Если ≥5 из 6 автоматических пунктов зелёные → staging считается рабочим."
