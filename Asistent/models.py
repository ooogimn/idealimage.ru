"""
Модели для приложения AI-Ассистент

⚠️  ВАЖНО: Этот файл теперь является оберткой для обратной совместимости.
Модели перенесены в пакет Asistent/models/:
  - tasks.py - ContentTask, TaskAssignment, AuthorTaskRejection, TaskHistory
  - ai.py - AIConversation, AIMessage, AITask, AIKnowledgeBase, AuthorNotification
  - content.py - AIGeneratedArticle, AuthorStyleProfile, ArticleGenerationMetric
  - moderation.py - BotProfile, BotActivity
  - finance.py - AuthorBalance, BonusFormula, BonusCalculation, DonationDistribution, AuthorDonationShare
  - templates.py - PromptTemplate, PromptTemplateVersion
  - stats.py - GigaChatUsageStats, GigaChatSettings, SystemLog, IntegrationEvent

Используйте: from Asistent.models import ModelName
"""

# Импорты всех моделей из нового пакета для обратной совместимости
from .models.base import TimestampMixin, StatusMixin
from .models.tasks import ContentTask, TaskAssignment, AuthorTaskRejection, TaskHistory
from .models.ai import AIConversation, AIMessage, AITask, AIKnowledgeBase, AuthorNotification
from .models.content import AIGeneratedArticle, AuthorStyleProfile, ArticleGenerationMetric
from .models.moderation import BotProfile, BotActivity
from .models.finance import AuthorBalance, BonusFormula, BonusCalculation, DonationDistribution, AuthorDonationShare
from .models.templates import PromptTemplate, PromptTemplateVersion
from .models.stats import GigaChatUsageStats, GigaChatSettings, SystemLog, IntegrationEvent

# Импорты из других подприложений
from .ChatBot_AI.models import ChatbotSettings, ChatbotFAQ, ChatMessage
from .moderations.models import ArticleModerationSettings, CommentModerationSettings, ModerationLog

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
        from .schedule.models import AISchedule
        return AISchedule
    elif name == 'AIScheduleRun':
        from .schedule.models import AIScheduleRun
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
