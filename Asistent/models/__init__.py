"""
Модели приложения Asistent

Структура:
- base.py - базовые модели и утилиты
- tasks.py - модели задач (ContentTask, TaskAssignment)
- ai.py - модели AI (AIConversation, AIMessage, AITask, AIKnowledgeBase)
- content.py - модели контента (AIGeneratedArticle, AuthorStyleProfile)
- moderation.py - модели модерации (BotProfile, BotActivity)
- finance.py - финансовые модели (BonusFormula, BonusCalculation, DonationDistribution)
- templates.py - шаблоны (PromptTemplate, PromptTemplateVersion)
- stats.py - статистика и логи (GigaChatUsageStats, GigaChatSettings, SystemLog, IntegrationEvent)

Для обратной совместимости все модели доступны через этот модуль.
"""

# Базовые модели
from .base import TimestampMixin, StatusMixin

# Модели задач
from .tasks import ContentTask, TaskAssignment, AuthorTaskRejection, TaskHistory

# Модели AI
from .ai import (
    AIConversation,
    AIMessage,
    AITask,
    AIKnowledgeBase,
    AuthorNotification,
)

# Модели контента
from .content import (
    AIGeneratedArticle,
    AuthorStyleProfile,
    ArticleGenerationMetric,
)

# Модели модерации
from .moderation import BotProfile, BotActivity

# Финансовые модели
from .finance import (
    AuthorBalance,
    BonusFormula,
    BonusCalculation,
    DonationDistribution,
    AuthorDonationShare,
)

# Шаблоны
from .templates import PromptTemplate, PromptTemplateVersion

# Статистика и логи
from .stats import (
    GigaChatUsageStats,
    GigaChatSettings,
    SystemLog,
    IntegrationEvent,
)

# Импорты из других подприложений (обратная совместимость)
from Asistent.ChatBot_AI.models import (
    ChatbotSettings,
    ChatbotFAQ,
    ChatMessage,
)

from Asistent.moderations.models import (
    ArticleModerationSettings,
    CommentModerationSettings,
    ModerationLog,
)

# Алиасы для обратной совместимости
ModerationCriteria = ArticleModerationSettings
CommentModerationCriteria = CommentModerationSettings
CommentModerationLog = ModerationLog

# Ленивый импорт моделей из schedule (для избежания циклических импортов)
def __getattr__(name):
    """
    Ленивый импорт моделей из schedule для обратной совместимости.
    Позволяет использовать: from Asistent.models import AISchedule
    """
    if name == 'AISchedule':
        from Asistent.schedule.models import AISchedule
        return AISchedule
    elif name == 'AIScheduleRun':
        from Asistent.schedule.models import AIScheduleRun
        return AIScheduleRun
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    # Base
    'TimestampMixin',
    'StatusMixin',
    # Tasks
    'ContentTask',
    'TaskAssignment',
    'AuthorTaskRejection',
    'TaskHistory',
    # AI
    'AIConversation',
    'AIMessage',
    'AITask',
    'AIKnowledgeBase',
    'AuthorNotification',
    # Content
    'AIGeneratedArticle',
    'AuthorStyleProfile',
    'ArticleGenerationMetric',
    # Moderation
    'BotProfile',
    'BotActivity',
    # Finance
    'AuthorBalance',
    'BonusFormula',
    'BonusCalculation',
    'DonationDistribution',
    'AuthorDonationShare',
    # Templates
    'PromptTemplate',
    'PromptTemplateVersion',
    # Stats
    'GigaChatUsageStats',
    'GigaChatSettings',
    'SystemLog',
    'IntegrationEvent',
    # ChatBot
    'ChatbotSettings',
    'ChatbotFAQ',
    'ChatMessage',
    # Moderations
    'ArticleModerationSettings',
    'CommentModerationSettings',
    'ModerationLog',
    # Aliases
    'ModerationCriteria',
    'CommentModerationCriteria',
    'CommentModerationLog',
]
