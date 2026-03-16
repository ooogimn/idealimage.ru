import logging
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Dict, Optional

from django.conf import settings
from django.utils import timezone
from django_celery_results.models import TaskResult

from Asistent.services.telegram_client import get_telegram_client

logger = logging.getLogger(__name__)


def check_djangoq_status() -> Dict:
    """
    Функция сохранена по имени, но возвращает статус Celery worker/results.
    """
    # LEGACY django_q 2026 migration
    try:
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)

        active_count = TaskResult.objects.filter(status='STARTED').count()
        queued_count = TaskResult.objects.filter(status='PENDING').count()
        recent_qs = TaskResult.objects.filter(date_done__gte=hour_ago, status='SUCCESS')
        recent_count = recent_qs.count()
        last_task = TaskResult.objects.filter(date_done__isnull=False).order_by('-date_done').first()

        process_running = False
        process_count = 0
        try:
            if sys.platform != "win32":
                result = subprocess.run(
                    ["pgrep", "-f", "celery.*worker"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    pids = [item for item in result.stdout.strip().split('\n') if item.strip()]
                    process_count = len(pids)
                    process_running = process_count > 0
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        except Exception as proc_error:
            logger.warning("Ошибка проверки celery worker процесса: %s", proc_error)

        if active_count > 0:
            is_running = True
            status_message = f"✅ Активно: {active_count} задач выполняется"
        elif recent_count > 0:
            is_running = True
            status_message = "✅ Работает: есть успешные задачи за последний час"
        elif process_running:
            is_running = True
            status_message = f"✅ Worker запущен ({process_count} процессов), ожидает задач"
        elif queued_count > 0:
            is_running = False
            status_message = f"⚠️ Очередь: {queued_count} задач ждут выполнения"
        else:
            is_running = False
            status_message = "❌ Worker остановлен"

        return {
            "is_running": is_running,
            "active_tasks": active_count,
            "queued_tasks": queued_count,
            "recent_tasks": recent_count,
            "last_task": last_task,
            "cluster_name": "celery-worker",
            "cluster_stat": None,
            "heartbeat": None,
            "heartbeat_age_seconds": None,
            "status_message": status_message,
            "checked_at": now,
            "process_count": process_count,
            "process_running": process_running,
        }
    except Exception as exc:
        logger.error("Ошибка проверки Celery статуса: %s", exc)
        return {
            "is_running": False,
            "active_tasks": 0,
            "queued_tasks": 0,
            "recent_tasks": 0,
            "last_task": None,
            "status_message": f"❌ Ошибка: {exc}",
            "error": str(exc),
            "process_count": 0,
            "process_running": False,
        }


def start_djangoq_cluster() -> Dict[str, Optional[int]]:
    """
    Имя сохранено, фактически запускается Celery worker.
    """
    # LEGACY django_q 2026 migration
    cwd = Path(settings.BASE_DIR)

    try:
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
            process = subprocess.Popen(
                ["celery", "-A", "IdealImage_PDJ", "worker", "-l", "info"],
                cwd=cwd,
                creationflags=creation_flags,
            )
        else:
            stdout_path = cwd / "logs" / "celery.worker.daemon.log"
            stdout_path.parent.mkdir(exist_ok=True)
            with open(stdout_path, "ab", buffering=0) as log_file:
                process = subprocess.Popen(
                    ["celery", "-A", "IdealImage_PDJ", "worker", "-l", "info"],
                    cwd=cwd,
                    stdout=log_file,
                    stderr=log_file,
                    start_new_session=True,
                )
        logger.info("🚀 Запущен celery worker (PID=%s)", process.pid)
        return {"success": True, "pid": process.pid}
    except Exception as exc:
        logger.error("❌ Не удалось запустить celery worker: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


def notify_admin_alert(message: str, severity: str = "info", prefix: str = "System") -> None:
    chat_id = getattr(settings, "ADMIN_ALERT_CHAT_ID", "") or getattr(settings, "CHAT_ID8", "")
    if not chat_id:
        logger.warning("ADMIN_ALERT_CHAT_ID не настроен, сообщение: %s", message)
        return

    prefix_icon = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
    }.get(severity, "ℹ️")

    title = prefix or "System"
    text = f"{prefix_icon} {title}: {message}\n⏱ {timezone.localtime().strftime('%d.%m %H:%M:%S')}"
    client = get_telegram_client()
    if not client.send_message(chat_id, text):
        logger.error("Не удалось отправить Telegram-уведомление: %s", text)


def notify_qcluster_alert(message: str, severity: str = "info") -> None:
    notify_admin_alert(message, severity=severity, prefix="Celery")
