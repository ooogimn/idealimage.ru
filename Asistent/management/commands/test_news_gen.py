"""
Прототип: тест генерации обычной статьи (не гороскопа) через UniversalContentGenerator.
Проверяет, можно ли переиспользовать код гороскопов для ad-hoc статей без расписания.

Запуск: python manage.py test_news_gen
"""
import logging
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from blog.models import Category, Post

User = get_user_model()
logger = logging.getLogger(__name__)

TOPIC = "Тренды весеннего макияжа 2026"
PROMPT_TEMPLATE_TEXT = (
    "Напиши увлекательную статью для женского журнала на тему: {topic}. "
    "Используй эмодзи, разбей на абзацы."
)


class Command(BaseCommand):
    help = 'Тест генерации статьи через UniversalContentGenerator (без расписания, черновик)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write('  Тест генерации статьи (не гороскоп)')
        self.stdout.write('=' * 60)

        # 1. Категория блога
        category = Category.objects.filter(
            title__icontains='красот'
        ).first() or Category.objects.filter(
            title__icontains='fashion'
        ).first() or Category.objects.first()
        if not category:
            self.stdout.write(self.style.ERROR('Нет ни одной категории в БД. Создайте категорию в админке.'))
            return
        self.stdout.write(f'  Категория: {category.title} (id={category.id})')

        # 2. Пользователь для created_by шаблона
        user = User.objects.filter(username='ai_assistant').first() or User.objects.filter(is_superuser=True).first()
        if not user:
            self.stdout.write(self.style.ERROR('Нет пользователя ai_assistant или superuser.'))
            return

        # 3. Шаблон промпта: ищем существующий не-гороскоп или создаём временный
        from Asistent.models import PromptTemplate

        template = PromptTemplate.objects.filter(
            category='article_single',
            is_active=True
        ).exclude(template__isnull=True).exclude(template='').first()

        if not template or '{topic}' not in (template.template or ''):
            self.stdout.write('  Создаём временный PromptTemplate для теста...')
            template = PromptTemplate(
                name='Тест новостей (test_news_gen)',
                category='article_single',
                template=PROMPT_TEMPLATE_TEXT,
                variables=['topic'],
                content_source_type='generate',
                image_source_type='none',
                blog_category=category,
                created_by=user,
                is_active=True,
            )
            template.save()
            self.stdout.write(self.style.SUCCESS(f'  Шаблон создан: id={template.id}'))
        else:
            self.stdout.write(f'  Используем существующий шаблон: {template.name} (id={template.id})')

        # 4. Конфиг: INTERACTIVE + preview_only=False → пост создаётся со статусом draft
        from Asistent.generators.universal import UniversalContentGenerator
        from Asistent.generators.base import GeneratorConfig, GeneratorMode

        config = GeneratorConfig(
            mode=GeneratorMode.INTERACTIVE,
            use_queue=False,
            use_heartbeat=False,
            use_priority=False,
            use_metrics=False,
            preview_only=False,
            retry_count=2,
            timeout=300,
        )

        # 5. Генератор без schedule_id (ad-hoc)
        try:
            generator = UniversalContentGenerator(
                template=template,
                config=config,
                schedule_id=None,
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'UniversalContentGenerator отказался: {e}'))
            logger.exception('init generator')
            return

        self.stdout.write('  Запуск генерации...')
        try:
            result = generator.generate(variables={'topic': TOPIC})
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка генерации: {e}'))
            logger.exception('generate')
            return

        if not result.success:
            self.stdout.write(self.style.ERROR(f'Генерация не удалась: {result.error}'))
            return

        post_id = result.post_id
        if not post_id:
            self.stdout.write(self.style.ERROR('Пост не создан (post_id пустой).'))
            return

        post = Post.objects.get(id=post_id)
        post.status = 'draft'
        post.save(update_fields=['status'])
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Успех! Пост создан: {post.id} {post.title}'))
        self.stdout.write(self.style.SUCCESS('Статус принудительно установлен в draft.'))
        self.stdout.write('=' * 60)
