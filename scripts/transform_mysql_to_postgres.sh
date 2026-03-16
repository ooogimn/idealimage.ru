#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# transform_mysql_to_postgres.sh
# Безопасный трансформер дампа MySQL -> PostgreSQL для Django-проекта
# Запуск: ./transform_mysql_to_postgres.sh input.sql [output.sql] [--dry-run]
# =============================================================================

INPUT_FILE="${1:-}"
OUTPUT_FILE="transformed_$(basename "$INPUT_FILE")"
DRY_RUN=""

if [[ "${2:-}" == "--dry-run" ]]; then
  DRY_RUN="--dry-run"
elif [[ -n "${2:-}" ]]; then
  OUTPUT_FILE="$2"
fi

if [[ "${3:-}" == "--dry-run" ]]; then
  DRY_RUN="--dry-run"
fi

if [[ -z "$INPUT_FILE" || ! -f "$INPUT_FILE" ]]; then
  echo "Использование: $0 dump_mysql.sql [transformed.sql] [--dry-run]"
  exit 1
fi

echo "┌──────────────────────────────────────────────────────────────┐"
echo "│  Трансформация дампа MySQL -> PostgreSQL                      │"
echo "│  Вход:  $INPUT_FILE                                          │"
echo "│  Выход: $OUTPUT_FILE                                         │"
echo "│  Режим: ${DRY_RUN:+DRY-RUN (только просмотр)}                │"
echo "└──────────────────────────────────────────────────────────────┘"

# 1. Создаём временный файл
TMP=$(mktemp)

# 2. Основные безопасные замены
echo "→ Выполняю базовые замены..."

sed -E '
  # 1. ENUM -> text (Django ChoiceField обычно text или varchar)
  s/enum\([^)]+\)/text/g;

  # 2. `backtick` -> "double quotes" (Postgres стандарт)
  s/`([^`]+)`/"\1"/g;

  # 3. GROUP_CONCAT -> string_agg
  s/GROUP_CONCAT\(/string_agg(/g;
  # NOTE: конвертацию SEPARATOR делаем вручную по dry-run, т.к. синтаксис MySQL
  # в дампах может отличаться и ломать sed в mingw.

  # 4. DATE_FORMAT -> to_char (безопасная унификация формата)
  s/DATE_FORMAT\(([^,]+),[^)]+\)/to_char(\1, '\''YYYY-MM-DD HH24:MI:SS'\'')/g;

  # 5. Убираем MySQL-специфичные директивы
  s/\)[[:space:]]+ENGINE=[^;]+;/);/g;
  /ENGINE=/d;
  /AUTO_INCREMENT=/d;
  /ZEROFILL/d;
  /ON DUPLICATE KEY UPDATE/d;
  s/ CHARACTER SET [^ ]+//g;
  s/ COLLATE [^ ]+//g;

  # 6. TINYINT(1) оставляем числовым (smallint), чтобы INSERT с 0/1
  # проходили без массового кастинга значений.
  s/ tinyint\(1\)( unsigned)?/ smallint/g;

  # 6.1 MySQL numeric display width -> PostgreSQL types
  s/\bbigint\([0-9]+\)/bigint/g;
  s/\bint\([0-9]+\)/integer/g;
  s/\bsmallint\([0-9]+\)/smallint/g;
  s/\bmediumint\([0-9]+\)/integer/g;
  s/\btinyint\([0-9]+\)/smallint/g;
  s/\bboolean\b/smallint/g;
  s/\bbool\b/smallint/g;
  s/ unsigned//g;
  s/ AUTO_INCREMENT//g;

  # 7. longtext -> text
  s/ longtext/ text/g;
  s/\bdatetime\(6\)/timestamp(6)/g;
  s/\bdatetime\b/timestamp/g;
  s/ ON UPDATE current_timestamp(\([0-9]+\))?//g;

  # 7.1 Удаляем MySQL JSON-проверки
  s/ CHECK \(json_valid\("[^"]+"\)\)//g;

  # 8. LEGACY: правило DEFAULT-кавычек отключено из-за shell-escaping в bash/mingw
  # Проверяется вручную на этапе dry-run.
' "$INPUT_FILE" > "$TMP"

# 2.1 MySQL-escape для апострофов внутри строк (\') -> PostgreSQL ('')
# Критично для русскоязычных текстов вида: "... название \'блант\' ..."
python - "$TMP" <<'PY'
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8", errors="replace")
text = text.replace("\\'", "''")
# MySQL charset prefix in string literals: _utf8mb4'...' -> '...'
text = text.replace("_utf8mb4'", "'")
# MySQL type alias not supported by PostgreSQL
text = re.sub(r"\bdouble\b", "double precision", text)
p.write_text(text, encoding="utf-8")
PY

# 2.2 Удаляем служебные MySQL директивы и lock/keys блоки, несовместимые с PostgreSQL
python - "$TMP" <<'PY'
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
out = []
in_create_table = False
last_non_empty = ""
for line in lines:
    s = line.strip()
    if re.match(r"^/\*!\d{5} .* \*/;?$", s):
        continue
    if s.startswith("LOCK TABLES ") or s == "UNLOCK TABLES;":
        continue
    if " DISABLE KEYS */;" in s or " ENABLE KEYS */;" in s:
        continue
    if "FOREIGN KEY" in s:
        # FK-констрейнты временно убираем: в MySQL-дампе порядок таблиц часто не гарантирует
        # наличие referenced-таблицы в момент CREATE TABLE.
        continue
    m_unique = re.match(r'^(\s*)UNIQUE KEY\s+"[^"]+"\s+\((.+)\)(,?)$', line)
    if m_unique:
        line = f'{m_unique.group(1)}UNIQUE ({m_unique.group(2)}){m_unique.group(3)}'
    elif re.match(r'^\s*KEY\s+"[^"]+"\s+\(.+\),?$', line):
        # Обычные индексы из дампа переносим миграциями/отдельными CREATE INDEX
        continue

    if line.lstrip().startswith("CREATE TABLE "):
        in_create_table = True
    elif in_create_table and s.startswith("--") and last_non_empty and not last_non_empty.endswith(");"):
        out.append(");")
        in_create_table = False
    elif in_create_table and s == ");":
        in_create_table = False

    out.append(line)
    if s:
        last_non_empty = s

if in_create_table and last_non_empty and not last_non_empty.endswith(");"):
    out.append(");")

text = "\n".join(out) + "\n"
# После удаления строк FK могут оставаться хвостовые запятые перед закрытием CREATE TABLE.
text = re.sub(r",\s*\n\);", "\n);", text)
p.write_text(text, encoding="utf-8")
PY

# 3. Проверка на опасные конструкции, которые могли остаться
echo "→ Проверка на остатки проблемных конструкций..."
DANGEROUS=$(grep -i -n -E "ON DUPLICATE|ENGINE=|AUTO_INCREMENT|ZEROFILL|GROUP_CONCAT" "$TMP" || true)

if [[ -n "$DANGEROUS" ]]; then
  echo "⚠️  ВНИМАНИЕ — найдены потенциально опасные строки:"
  echo "$DANGEROUS"
  echo "Рекомендую открыть $TMP и проверить эти строки вручную."
else
  echo "✓ Опасные конструкции не найдены — чисто"
fi

# 4. Dry-run режим — показываем первые строки и diff
if [[ -n "$DRY_RUN" ]]; then
  echo
  echo "Dry-run: первые 40 строк результата"
  head -n 40 "$TMP"
  echo "..."
  echo
  echo "Diff первых 200 строк:"
  diff -u <(head -n 200 "$INPUT_FILE") <(head -n 200 "$TMP") || true
  rm "$TMP"
  exit 0
fi

# 5. Финальное сохранение
mv "$TMP" "$OUTPUT_FILE"
echo
echo "✓ Трансформация завершена"
echo "   Размер результата: $(du -h "$OUTPUT_FILE" | cut -f1)"
echo "   Следующий шаг:"
echo "   cat $OUTPUT_FILE | docker-compose -f docker-compose.staging.yml exec -T postgres psql -U \$POSTGRES_USER -d \$POSTGRES_DB"
echo
echo "Рекомендация: перед загрузкой в PostgreSQL сделайте ещё один grep:"
echo "   grep -i -E 'enum|GROUP_CONCAT|ON DUPLICATE' $OUTPUT_FILE"
