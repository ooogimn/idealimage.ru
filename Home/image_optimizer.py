"""
🚀 Прокси для ImageOptimizer
Использует унифицированный оптимизатор из utilits
"""
from utilits.image_optimizer import ImageOptimizer, optimize_landing_image

# Для обратной совместимости, если где-то импортируется напрямую
__all__ = ['ImageOptimizer', 'optimize_landing_image']
