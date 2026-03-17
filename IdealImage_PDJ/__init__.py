"""
IdealImage Project
"""
from __future__ import absolute_import, unicode_literals

# Инициализация Celery — запускается вместе с Django
from .celery import app as celery_app

__all__ = ('celery_app',)
