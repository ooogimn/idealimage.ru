"""
Management команда: создание базовых рекламных мест (в т.ч. sidebar_right для сайдбара статьи).
Запуск: python manage.py init_ad_places
"""
from django.core.management.base import BaseCommand
from advertising.models import AdPlace


class Command(BaseCommand):
    help = 'Создать рекламное место sidebar_right, если его ещё нет'

    def handle(self, *args, **options):
        code = 'sidebar_right'
        place, created = AdPlace.objects.get_or_create(
            code=code,
            defaults={
                'name': 'Сайдбар справа',
                'description': 'Рекламный блок в правом сайдбаре на странице статьи',
                'placement_type': 'banner',
                'recommended_size': '300x250',
                'position_order': 24,
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"AdPlace '{code}' создан."))
        else:
            self.stdout.write(f"AdPlace '{code}' уже существовал.")
        self.stdout.write(self.style.SUCCESS("AdPlace 'sidebar_right' готов."))
