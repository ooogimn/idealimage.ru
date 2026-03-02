"""
Проверка генерации изображений для гороскопов
Использование: python manage.py check_horoscope_images
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from blog.models import Post
from Asistent.models import SystemLog


class Command(BaseCommand):
    help = 'Проверка генерации изображений для гороскопов'

    def handle(self, *args, **options):
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('ПРОВЕРКА ГОРОСКОПОВ И ИЗОБРАЖЕНИЙ'))
        self.stdout.write('='*60 + '\n')
        
        # 1. Последние гороскопы за 2 часа
        self.stdout.write(self.style.WARNING('\n1. ПОСЛЕДНИЕ ГОРОСКОПЫ (за 2 часа):'))
        self.stdout.write('-'*60)
        
        posts = Post.objects.filter(
            title__icontains='гороскоп',
            created_at__gte=timezone.now() - timedelta(hours=2)
        ).order_by('-created_at')[:20]
        
        if not posts.exists():
            self.stdout.write(self.style.WARNING('   Нет гороскопов за последние 2 часа'))
        else:
            with_image = 0
            without_image = 0
            
            for post in posts:
                has_image = bool(post.kartinka)
                if has_image:
                    with_image += 1
                    status = self.style.SUCCESS('ЕСТЬ')
                else:
                    without_image += 1
                    status = self.style.ERROR('НЕТ')
                
                self.stdout.write(
                    f'   ID: {post.id:4d} | {status} | {post.title[:50]:50s} | {post.created_at.strftime("%H:%M:%S")}'
                )
            
            self.stdout.write('-'*60)
            self.stdout.write(f'   Всего: {posts.count()}')
            self.stdout.write(self.style.SUCCESS(f'   С изображением: {with_image}'))
            self.stdout.write(self.style.ERROR(f'   Без изображения: {without_image}'))
        
        # 2. Логи генерации гороскопов
        self.stdout.write(self.style.WARNING('\n2. ЛОГИ ГЕНЕРАЦИИ ГОРОСКОПОВ (за 30 минут):'))
        self.stdout.write('-'*60)
        
        horoscope_logs = SystemLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(minutes=30),
            message__icontains='гороскоп'
        ).order_by('-timestamp')[:15]
        
        if not horoscope_logs.exists():
            self.stdout.write(self.style.WARNING('   Нет логов за последние 30 минут'))
        else:
            for log in horoscope_logs:
                level_style = self.style.ERROR if log.level == 'ERROR' else self.style.WARNING if log.level == 'WARNING' else ''
                self.stdout.write(
                    f'   {log.timestamp.strftime("%H:%M:%S")} [{log.level:7s}] {log.message[:150]}',
                    style=level_style
                )
        
        # 3. Логи генерации изображений
        self.stdout.write(self.style.WARNING('\n3. ЛОГИ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ (за 30 минут):'))
        self.stdout.write('-'*60)
        
        image_logs = SystemLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(minutes=30)
        ).filter(
            message__icontains='изображение'
        ).order_by('-timestamp')[:15]
        
        if not image_logs.exists():
            self.stdout.write(self.style.WARNING('   Нет логов генерации изображений'))
        else:
            for log in image_logs:
                if '✅' in log.message or 'Изображение сохранено' in log.message:
                    style = self.style.SUCCESS
                elif '❌' in log.message or 'ERROR' in log.level:
                    style = self.style.ERROR
                elif '⚠️' in log.message or 'WARNING' in log.level:
                    style = self.style.WARNING
                else:
                    style = None
                
                self.stdout.write(
                    f'   {log.timestamp.strftime("%H:%M:%S")} [{log.level:7s}] {log.message[:150]}',
                    style=style
                )
        
        # 4. Ошибки
        self.stdout.write(self.style.WARNING('\n4. ОШИБКИ ПРИ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ (за 30 минут):'))
        self.stdout.write('-'*60)
        
        errors = SystemLog.objects.filter(
            timestamp__gte=timezone.now() - timedelta(minutes=30),
            level__in=['ERROR', 'WARNING', 'CRITICAL']
        ).filter(
            message__icontains='изображение'
        ).order_by('-timestamp')[:10]
        
        if not errors.exists():
            self.stdout.write(self.style.SUCCESS('   Ошибок не найдено'))
        else:
            for error in errors:
                self.stdout.write(
                    f'   {error.timestamp.strftime("%H:%M:%S")} [{error.level:7s}] {error.message[:200]}',
                    style=self.style.ERROR
                )
        
        # 5. Статистика за 24 часа
        self.stdout.write(self.style.WARNING('\n5. СТАТИСТИКА ЗА 24 ЧАСА:'))
        self.stdout.write('-'*60)
        
        day_posts = Post.objects.filter(
            title__icontains='гороскоп',
            created_at__gte=timezone.now() - timedelta(hours=24)
        )
        
        day_with_image = day_posts.exclude(kartinka__isnull=True).exclude(kartinka='').count()
        day_without_image = day_posts.filter(kartinka__isnull=True).count() + day_posts.filter(kartinka='').count()
        
        self.stdout.write(f'   Всего гороскопов: {day_posts.count()}')
        self.stdout.write(self.style.SUCCESS(f'   С изображением: {day_with_image}'))
        self.stdout.write(self.style.ERROR(f'   Без изображения: {day_without_image}'))
        
        if day_posts.count() > 0:
            percent = (day_with_image / day_posts.count()) * 100
            self.stdout.write(f'   Процент успеха: {percent:.1f}%')
        
        self.stdout.write('\n' + '='*60 + '\n')
