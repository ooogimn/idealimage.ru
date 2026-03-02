"""
Management команда для установки интервала между гороскопами
"""
from django.core.management.base import BaseCommand
from Asistent.schedule.models import AISchedule
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Устанавливает интервал между генерацией гороскопов (в секундах)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=300,
            help='Интервал в секундах (по умолчанию: 300 = 5 минут)'
        )
        parser.add_argument(
            '--schedule-id',
            type=int,
            help='ID конкретного расписания (если не указано - все активные гороскопы)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Только показать что будет изменено, без сохранения'
        )

    def handle(self, *args, **options):
        interval = options.get('interval', 300)
        schedule_id = options.get('schedule_id')
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  [SET INTERVAL] УСТАНОВКА ИНТЕРВАЛА МЕЖДУ ГОРОСКОПАМИ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY-RUN] РЕЖИМ ПРЕДПРОСМОТРА (изменения не будут сохранены)'))
            self.stdout.write('')
        
        self.stdout.write(f'[INFO] Устанавливаемый интервал: {interval} секунд ({interval // 60} минут)')
        self.stdout.write('')
        
        # Ищем расписания
        if schedule_id:
            try:
                schedules = [AISchedule.objects.get(id=schedule_id)]
            except AISchedule.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'[ERROR] Расписание ID={schedule_id} не найдено!'))
                return
        else:
            schedules = AISchedule.objects.filter(
                prompt_template__category='horoscope',
                is_active=True
            ).select_related('prompt_template')
        
        if not schedules:
            self.stdout.write(self.style.ERROR('[ERROR] Активные расписания гороскопов не найдены!'))
            return
        
        self.stdout.write(f'[INFO] Найдено расписаний: {len(schedules)}')
        self.stdout.write('')
        
        updated_count = 0
        
        for schedule in schedules:
            payload = schedule.payload_template or {}
            old_delay = payload.get('generation_delay', 20)
            
            self.stdout.write(f'[SCHEDULE] Расписание ID={schedule.id}: {schedule.name}')
            self.stdout.write(f'   Текущий интервал: {old_delay} секунд')
            
            if old_delay == interval:
                self.stdout.write(self.style.WARNING(f'   [SKIP] Интервал уже установлен ({interval}с), пропуск'))
                self.stdout.write('')
                continue
            
            if not dry_run:
                payload['generation_delay'] = interval
                schedule.payload_template = payload
                schedule.save(update_fields=['payload_template'])
                self.stdout.write(self.style.SUCCESS(f'   [OK] Обновлено: {old_delay}с → {interval}с'))
                updated_count += 1
            else:
                self.stdout.write(f'   [PREVIEW] Будет обновлено: {old_delay}с → {interval}с')
            
            self.stdout.write('')
        
        self.stdout.write('=' * 70)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[PREVIEW] ПРЕДПРОСМОТР: Будет обновлено расписаний: {updated_count if not dry_run else len([s for s in schedules if (s.payload_template or {}).get("generation_delay", 20) != interval])}'
            ))
            self.stdout.write('   Для применения изменений запустите без --dry-run')
        else:
            self.stdout.write(self.style.SUCCESS(
                f'[OK] Обновлено расписаний: {updated_count}'
            ))
        self.stdout.write('=' * 70)
        
        if updated_count > 0 and not dry_run:
            self.stdout.write('')
            self.stdout.write('[INFO] Следующий запуск будет использовать новый интервал')
