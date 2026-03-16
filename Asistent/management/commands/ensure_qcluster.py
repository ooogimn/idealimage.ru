"""
Команда для проверки и автозапуска Celery worker.
"""
# LEGACY django_q 2026 migration: имя команды сохранено для обратной совместимости.
import os
import sys
import subprocess
import time
from django.core.management.base import BaseCommand
from django_celery_results.models import TaskResult
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Проверяет работу Celery worker и запускает его при необходимости'

    def add_arguments(self, parser):
        parser.add_argument(
            '--monitor',
            action='store_true',
            help='Режим мониторинга (проверка каждые 60 секунд)',
        )

    def handle(self, *args, **options):
        monitor_mode = options.get('monitor', False)
        
        if monitor_mode:
            self.stdout.write(self.style.WARNING('🔄 Режим мониторинга Celery'))
            self.stdout.write('Проверка каждые 60 секунд. Ctrl+C для выхода.\n')
            
            try:
                while True:
                    self._check_and_start()
                    time.sleep(60)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('\n⚠️ Мониторинг остановлен'))
        else:
            self._check_and_start()

    def _check_and_start(self):
        """Проверяет и запускает Celery worker при необходимости"""
        is_running = self._is_qcluster_running()
        
        if is_running:
            self.stdout.write(self.style.SUCCESS('✅ Celery worker работает'))
            self._show_stats()
        else:
            self.stdout.write(self.style.ERROR('❌ Celery worker не запущен'))
            
            # Пытаемся запустить
            if self._start_qcluster():
                self.stdout.write(self.style.SUCCESS('✅ Celery worker запущен'))
                time.sleep(3)  # Даём время на старт
                
                if self._is_qcluster_running():
                    self.stdout.write(self.style.SUCCESS('✅ Подтверждено: Cluster работает'))
                else:
                    self.stdout.write(self.style.ERROR('❌ Не удалось запустить Cluster'))
                    self.stdout.write('Запустите вручную: celery -A IdealImage_PDJ worker -l info')
            else:
                self.stdout.write(self.style.ERROR('❌ Ошибка запуска Cluster'))

    def _is_qcluster_running(self):
        """Проверяет активность Celery worker по последним задачам"""
        try:
            # Проверяем наличие недавних задач (последние 5 минут)
            recent_time = timezone.now() - timedelta(minutes=5)
            recent_tasks = TaskResult.objects.filter(
                date_done__gte=recent_time
            ).exists()
            
            # Или активные задачи (выполняются сейчас)
            active_tasks = TaskResult.objects.filter(
                status='STARTED'
            ).exists()
            
            return recent_tasks or active_tasks
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка проверки: {e}'))
            return False

    def _start_qcluster(self):
        """Запускает Celery worker в фоне"""
        try:
            if sys.platform == 'win32':
                # Windows - в новом окне консоли
                subprocess.Popen(
                    ['celery', '-A', 'IdealImage_PDJ', 'worker', '-l', 'info'],
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:
                # Linux/Mac - в фоне с перенаправлением вывода
                subprocess.Popen(
                    ['celery', '-A', 'IdealImage_PDJ', 'worker', '-l', 'info'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка запуска: {e}'))
            return False

    def _show_stats(self):
        """Показывает статистику задач"""
        try:
            active = TaskResult.objects.filter(
                status='STARTED'
            ).count()
            
            queued = TaskResult.objects.filter(
                status='PENDING'
            ).count()
            
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            completed_today = TaskResult.objects.filter(
                date_done__gte=today_start,
                status='SUCCESS'
            ).count()
            
            self.stdout.write(f'   Выполняется: {active}')
            self.stdout.write(f'   В очереди: {queued}')
            self.stdout.write(f'   Выполнено сегодня: {completed_today}')
        except Exception:
            pass

