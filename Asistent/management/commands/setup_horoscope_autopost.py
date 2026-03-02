"""
Команда для настройки автопостинга гороскопов
Создает расписание: каждые 15 минут с 8:00 до 10:45, 12 раз в день
Использует шаблон промпта DAILY_HOROSCOPE_PROMPT вместо пайплайна
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command
from Asistent.models import AISchedule, PromptTemplate  # AISchedule через __getattr__
from blog.models import Category
from django.utils import timezone
from datetime import time
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Настройка автопостинга гороскопов: каждые 15 минут с 8:00, 12 раз в день (через шаблон промпта)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Пересоздать расписание даже если оно уже существует'
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  🔮 НАСТРОЙКА АВТОПОСТИНГА ГОРОСКОПОВ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        
        # Удаляем ВСЕ старые расписания с пайплайном
        self.stdout.write('🗑️ Удаление старых расписаний с пайплайном...')
        old_schedules = AISchedule.objects.filter(
            pipeline_slug="daily-horoscope-flow"
        )
        old_count = old_schedules.count()
        if old_count > 0:
            old_schedules.delete()
            self.stdout.write(self.style.WARNING(
                f'   Удалено {old_count} старых расписаний с пайплайном'
            ))
        else:
            self.stdout.write('   Старых расписаний не найдено')
        
        # Проверяем шаблон промпта
        self.stdout.write('')
        self.stdout.write('🔍 Проверка шаблона промпта...')
        prompt_template = PromptTemplate.objects.filter(
            name="DAILY_HOROSCOPE_PROMPT",
            is_active=True
        ).first()
        
        if not prompt_template:
            self.stdout.write(self.style.ERROR(
                '❌ Шаблон промпта "DAILY_HOROSCOPE_PROMPT" не найден или неактивен!'
            ))
            self.stdout.write('   Создайте шаблон промпта в админке: /admin/Asistent/prompttemplate/')
            return
        
        self.stdout.write(self.style.SUCCESS(
            f'✅ Шаблон промпта найден: {prompt_template.name}'
        ))
        self.stdout.write('')
        
        # Получаем категорию
        try:
            category = Category.objects.get(slug="intellektualnye-prognozy")
        except Category.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                '❌ Категория "intellektualnye-prognozy" не найдена!'
            ))
            return
        
        # Проверяем существующие расписания с шаблоном промпта
        existing_schedules = AISchedule.objects.filter(
            prompt_template=prompt_template,
            name__contains="Автопостинг гороскопов"
        )
        
        if existing_schedules.exists() and not force:
            self.stdout.write(self.style.WARNING(
                f'⚠️ Найдено существующее расписание: {existing_schedules.first().name}'
            ))
            self.stdout.write('   Используйте --force для пересоздания')
            return
        
        # Удаляем старые расписания если force
        if force and existing_schedules.exists():
            count = existing_schedules.count()
            existing_schedules.delete()
            self.stdout.write(self.style.WARNING(
                f'🗑️ Удалено {count} старых расписаний'
            ))
        
        # Создаем расписание с cron выражением для всех нужных времен
        cron_expressions = [
            "0 8 * * *",   # 8:00
            "15 8 * * *",  # 8:15
            "30 8 * * *",  # 8:30
            "45 8 * * *",  # 8:45
            "0 9 * * *",   # 9:00
            "15 9 * * *",  # 9:15
            "30 9 * * *",  # 9:30
            "45 9 * * *",  # 9:45
            "0 10 * * *",  # 10:00
            "15 10 * * *", # 10:15
            "30 10 * * *", # 10:30
            "45 10 * * *", # 10:45
        ]
        
        created_count = 0
        for i, cron_expr in enumerate(cron_expressions, 1):
            schedule_name = f"Автопостинг гороскопов #{i} ({cron_expr})"
            
            # Проверяем, не существует ли уже такое расписание
            if AISchedule.objects.filter(name=schedule_name).exists() and not force:
                self.stdout.write(self.style.WARNING(
                    f'  ⏭️ Пропущено: {schedule_name} (уже существует)'
                ))
                continue
            
            # Парсим время из cron
            parts = cron_expr.split()
            minute = int(parts[0])
            hour = int(parts[1])
            scheduled_time = time(hour, minute)
            
            schedule = AISchedule.objects.create(
                name=schedule_name,
                strategy_type="prompt",  # Используем стратегию промпта
                prompt_template=prompt_template,  # Привязываем шаблон промпта
                category=category,
                schedule_kind="cron",
                cron_expression=cron_expr,
                scheduled_time=scheduled_time,
                articles_per_run=1,
                is_active=True,
                payload_template={
                    "target_date_offset": 1,  # Прогноз на завтра
                    "publish_mode": "published",  # Сразу публикуем
                    "title_template": "{zodiac_sign} — гороскоп на {horoscope_target_date_display}",
                    "description_template": "Ежедневный гороскоп для {zodiac_sign} на {horoscope_target_date_display}.",
                    "base_tags": ["гороскоп", "прогноз на завтра"],
                    "prompt_name": "DAILY_HOROSCOPE_PROMPT",
                    "image_prompt_name": "HOROSCOPE_IMAGE_PROMPT",
                }
            )
            
            # Вычисляем следующий запуск
            schedule.update_next_run()
            
            created_count += 1
            self.stdout.write(self.style.SUCCESS(
                f'  ✅ Создано: {schedule_name}'
            ))
            self.stdout.write(f'     Следующий запуск: {schedule.next_run}')
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'✨ Создано расписаний: {created_count}'
        ))
        self.stdout.write('')
        
        # Синхронизируем с Django-Q
        self.stdout.write('🔄 Синхронизация с Django-Q...')
        try:
            call_command('sync_schedules', '--force')
            self.stdout.write(self.style.SUCCESS(
                '✅ Расписание синхронизировано с Django-Q'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f'❌ Ошибка синхронизации: {e}'
            ))
            logger.error(f"Ошибка синхронизации расписаний: {e}", exc_info=True)
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  ✅ НАСТРОЙКА ЗАВЕРШЕНА'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write('📋 Проверьте расписания:')
        self.stdout.write('   - Админка: /admin/Asistent/aischedule/')
        self.stdout.write('   - Django-Q: /admin/django_q/schedule/')
        self.stdout.write('')
        self.stdout.write('⚠️ ВАЖНО: Убедитесь, что Django-Q запущен:')
        self.stdout.write('   python manage.py qcluster')

