"""
Команда для настройки автоматического SEO мониторинга через Celery Beat.
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule


class Command(BaseCommand):
    help = 'Настройка автоматического мониторинга 404 ошибок'
    
    def handle(self, *args, **options):
        # LEGACY django_q 2026 migration
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=360,
            period=IntervalSchedule.MINUTES,
        )
        schedule, created = PeriodicTask.objects.get_or_create(
            name='SEO 404 Monitor',
            defaults={
                'task': 'Asistent.seo_monitor.run_seo_404_monitor',
                'interval': interval,
                'enabled': True,
            },
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS('[OK] SEO мониторинг настроен (каждые 6 часов)'))
        else:
            self.stdout.write(self.style.WARNING('[!] SEO мониторинг уже существует'))
            schedule.task = 'Asistent.seo_monitor.run_seo_404_monitor'
            schedule.interval = interval
            schedule.enabled = True
            schedule.save()
            self.stdout.write(self.style.SUCCESS('[OK] SEO мониторинг обновлён'))
        
        self.stdout.write(self.style.SUCCESS('\n[INFO] Следующие шаги:'))
        self.stdout.write('1. Убедитесь, что Celery worker/beat запущены')
        self.stdout.write('2. Настройте переменные окружения в .env:')
        self.stdout.write('   - YANDEX_WEBMASTER_TOKEN')
        self.stdout.write('   - YANDEX_WEBMASTER_USER_ID')
        self.stdout.write('   - YANDEX_WEBMASTER_HOST_ID')
        self.stdout.write('\n3. Или запустите первую проверку вручную:')
        self.stdout.write('   python manage.py check_seo')

