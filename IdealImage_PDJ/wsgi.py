"""
WSGI config for IdealImage_PDJ project.
"""

import os
from decouple import config
from django.core.wsgi import get_wsgi_application

# PyMySQL как замена mysqlclient — до запуска Django
if config('DB_ENGINE', default='postgresql') == 'mysql':
    try:
        import pymysql
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')

application = get_wsgi_application()