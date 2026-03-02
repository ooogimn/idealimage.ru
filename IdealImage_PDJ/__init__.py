"""
IdealImage Project
"""
from __future__ import absolute_import, unicode_literals
import os

# PyMySQL как замена mysqlclient (только для MySQL режима)
if os.environ.get('DB_ENGINE', 'postgresql') == 'mysql':
    try:
        import pymysql
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass

# Инициализация Celery — запускается вместе с Django
from .celery import app as celery_app

__all__ = ('celery_app',)
