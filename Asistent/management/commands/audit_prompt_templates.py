"""
Аудит промпт-шаблонов: список всех шаблонов и извлечённых из них динамических переменных.

Часть ТЗ №1 (Ideal Engine): анализ текущих шаблонов для подготовки дашборда к подстановке переменных.
"""
from django.core.management.base import BaseCommand

from Asistent.models import PromptTemplate


class Command(BaseCommand):
    help = 'Аудит PromptTemplate: вывод списка шаблонов и динамических переменных в них'

    def add_arguments(self, parser):
        parser.add_argument(
            '--active-only',
            action='store_true',
            help='Показать только активные шаблоны',
        )
        parser.add_argument(
            '--ids',
            type=str,
            metavar='ID[,ID,...]',
            help='Показать только шаблоны с указанными ID (через запятую)',
        )

    def handle(self, *args, **options):
        qs = PromptTemplate.objects.all().order_by('category', 'name')
        if options.get('active_only'):
            qs = qs.filter(is_active=True)
        if options.get('ids'):
            raw = options['ids'].strip().split(',')
            ids = [int(x.strip()) for x in raw if x.strip().isdigit()]
            if ids:
                qs = qs.filter(pk__in=ids)

        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('  АУДИТ ПРОМПТ-ШАБЛОНОВ — ДИНАМИЧЕСКИЕ ПЕРЕМЕННЫЕ'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')

        total = 0
        for t in qs:
            total += 1
            variables = t.get_template_variables()
            status = '✅' if t.is_active else '⏸'
            self.stdout.write(
                f'{status} #{t.pk} {t.name or "(без названия)"} [{t.get_category_display()}]'
            )
            self.stdout.write(f'   Переменные ({len(variables)}): {", ".join(variables) or "—"}')
            self.stdout.write('')

        self.stdout.write(self.style.SUCCESS(f'Всего шаблонов: {total}'))
