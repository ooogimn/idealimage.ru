import gzip
import os
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Создаёт резервную копию PostgreSQL базы данных в каталог backups/db."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention-days",
            type=int,
            default=14,
            help="Сколько дней хранить резервные копии (по умолчанию 14).",
        )

    def handle(self, *args, **options):
        db_settings = settings.DATABASES.get("default", {})
        if "postgresql" not in db_settings.get("ENGINE", ""):
            raise CommandError("Команда поддерживает только PostgreSQL подключение.")

        backup_dir = Path(settings.BASE_DIR) / "backups" / "db"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        file_path = backup_dir / f"db_backup_{timestamp}.sql.gz"

        host = db_settings.get("HOST") or "localhost"
        port = str(db_settings.get("PORT") or "5432")
        user = db_settings.get("USER")
        name = db_settings.get("NAME")
        password = db_settings.get("PASSWORD", "")

        pg_dump_cmd = [
            "pg_dump",
            f"--host={host}",
            f"--port={port}",
            f"--user={user}",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            "--encoding=UTF8",
            name,
        ]

        self.stdout.write(f"📦 Создаю резервную копию базы {name} → {file_path}")

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        try:
            with gzip.open(file_path, "wb") as archive:
                result = subprocess.run(
                    pg_dump_cmd,
                    stdout=archive,
                    stderr=subprocess.PIPE,
                    env=env,
                    check=False,
                )
        except FileNotFoundError as exc:
            raise CommandError("pg_dump не найден в PATH") from exc

        if result.returncode != 0:
            file_path.unlink(missing_ok=True)
            raise CommandError(f"pg_dump завершился с ошибкой: {result.stderr.decode('utf-8', errors='ignore')}")

        self.stdout.write(self.style.SUCCESS("✅ Бэкап успешно создан"))

        retention_days = options["retention_days"]
        self._cleanup_old_backups(backup_dir, retention_days)

    def _cleanup_old_backups(self, backup_dir: Path, retention_days: int) -> None:
        cutoff = timezone.now() - timedelta(days=retention_days)
        removed = 0
        for file in backup_dir.glob("db_backup_*.sql.gz"):
            if timezone.datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc) < cutoff:
                file.unlink(missing_ok=True)
                removed += 1
        if removed:
            self.stdout.write(f"🧹 Удалено устаревших бэкапов: {removed}")


