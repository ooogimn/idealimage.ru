"""
Команда для автоматической генерации и публикации всех 12 гороскопов
Генерирует гороскопы для всех знаков зодиака по очереди и сразу публикует их на сайте
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from Asistent.models import PromptTemplate
from Asistent.generators.universal import UniversalContentGenerator
from Asistent.generators.base import GeneratorConfig, GeneratorMode
from Asistent.constants import ZODIAC_SIGNS
import logging
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Генерирует и публикует все 12 гороскопов для всех знаков зодиака'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Тестовый запуск без публикации (только генерация)'
        )
        parser.add_argument(
            '--delay',
            type=int,
            default=5,
            help='Задержка между генерацией гороскопов в секундах (по умолчанию: 5)'
        )
        parser.add_argument(
            '--template-id',
            type=int,
            help='ID промпт-шаблона (по умолчанию: DAILY_HOROSCOPE_PROMPT)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Максимум знаков для генерации (для теста: --limit=1)'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        delay = options.get('delay', 5)
        template_id = options.get('template_id')
        limit = options.get('limit')
        
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  🔮 ГЕНЕРАЦИЯ И ПУБЛИКАЦИЯ ВСЕХ ГОРОСКОПОВ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️ РЕЖИМ ТЕСТИРОВАНИЯ (без публикации)'))
            self.stdout.write('')
        
        # Получаем шаблон промпта
        if template_id:
            try:
                template = PromptTemplate.objects.get(id=template_id, is_active=True)
            except PromptTemplate.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f'❌ Промпт-шаблон с ID {template_id} не найден или неактивен!'
                ))
                return
        else:
            template = PromptTemplate.objects.filter(
                name="DAILY_HOROSCOPE_PROMPT",
                is_active=True
            ).first()
            
            if not template:
                self.stdout.write(self.style.ERROR(
                    '❌ Промпт-шаблон "DAILY_HOROSCOPE_PROMPT" не найден или неактивен!'
                ))
                return
        
        self.stdout.write(self.style.SUCCESS(
            f'✅ Используется шаблон: {template.name} (ID: {template.id})'
        ))
        self.stdout.write('')
        
        # Создаем конфиг для автоматической публикации
        if dry_run:
            config = GeneratorConfig.for_interactive()  # Preview режим
        else:
            config = GeneratorConfig.for_auto()  # Автоматическая публикация
            config.preview_only = False  # Публикуем сразу
        
        # Ограничиваем количество знаков при --limit
        signs_to_run = ZODIAC_SIGNS[:limit] if limit else ZODIAC_SIGNS
        
        # Статистика
        results = {
            'total': len(signs_to_run),
            'success': 0,
            'failed': 0,
            'posts': [],
            'errors': []
        }
        
        self.stdout.write(f'📋 Будет сгенерировано гороскопов: {results["total"]}')
        self.stdout.write(f'⏱️ Задержка между генерациями: {delay} секунд')
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        
        # Генерируем гороскопы для каждого знака
        for i, zodiac_sign in enumerate(signs_to_run, 1):
            self.stdout.write(self.style.SUCCESS(
                f'[{i}/{results["total"]}] 🔮 Генерация гороскопа для {zodiac_sign}...'
            ))
            
            try:
                # Создаем генератор
                generator = UniversalContentGenerator(template, config)
                
                # Переменные для генерации
                variables = {
                    'zodiac_sign': zodiac_sign,
                    'zodiac': zodiac_sign,  # Альтернативное имя
                }
                
                # Генерируем контент
                result = generator.generate(variables=variables)
                
                if result.success:
                    if dry_run:
                        self.stdout.write(self.style.SUCCESS(
                            f'   ✅ Сгенерировано (тест): {result.title}'
                        ))
                        self.stdout.write(f'   📝 Контент: {len(result.content)} символов')
                    else:
                        post_id = result.post_id if result.post else None
                        post_url = f'/blog/{result.post.slug}/' if result.post else None
                        
                        results['success'] += 1
                        results['posts'].append({
                            'zodiac': zodiac_sign,
                            'post_id': post_id,
                            'title': result.title,
                            'url': post_url
                        })
                        
                        self.stdout.write(self.style.SUCCESS(
                            f'   ✅ Опубликовано! Post ID: {post_id}'
                        ))
                        self.stdout.write(f'   📝 Заголовок: {result.title}')
                        if post_url:
                            self.stdout.write(f'   🔗 URL: {post_url}')
                
                else:
                    error_msg = result.error or 'Неизвестная ошибка'
                    results['failed'] += 1
                    results['errors'].append({
                        'zodiac': zodiac_sign,
                        'error': error_msg
                    })
                    
                    self.stdout.write(self.style.ERROR(
                        f'   ❌ Ошибка: {error_msg}'
                    ))
                    logger.error(f"Ошибка генерации гороскопа для {zodiac_sign}: {error_msg}")
            
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'zodiac': zodiac_sign,
                    'error': str(e)
                })
                
                self.stdout.write(self.style.ERROR(
                    f'   ❌ Исключение: {str(e)}'
                ))
                logger.exception(f"Критическая ошибка генерации гороскопа для {zodiac_sign}")
            
            # Задержка между генерациями (кроме последнего)
            if i < results['total']:
                self.stdout.write(f'   ⏳ Ожидание {delay} секунд...')
                time.sleep(delay)
            
            self.stdout.write('')
        
        # Итоговая статистика
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('  📊 ИТОГОВАЯ СТАТИСТИКА'))
        self.stdout.write('=' * 70)
        self.stdout.write('')
        self.stdout.write(f'✅ Успешно: {results["success"]}/{results["total"]}')
        self.stdout.write(f'❌ Ошибок: {results["failed"]}/{results["total"]}')
        self.stdout.write('')
        
        if results['posts']:
            self.stdout.write(self.style.SUCCESS('📝 Опубликованные посты:'))
            for post_info in results['posts']:
                self.stdout.write(
                    f'   - {post_info["zodiac"]}: Post ID {post_info["post_id"]} '
                    f'({post_info["title"][:50]}...)'
                )
            self.stdout.write('')
        
        if results['errors']:
            self.stdout.write(self.style.WARNING('⚠️ Ошибки:'))
            for error_info in results['errors']:
                self.stdout.write(
                    f'   - {error_info["zodiac"]}: {error_info["error"]}'
                )
            self.stdout.write('')
        
        self.stdout.write('=' * 70)
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                '⚠️ Это был тестовый запуск. Для реальной публикации запустите без --dry-run'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Генерация завершена! Опубликовано {results["success"]} гороскопов'
            ))

