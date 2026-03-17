"""
WSGI config for IdealImage_PDJ project.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')

application = get_wsgi_application()