#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# PyMySQL как замена mysqlclient — до запуска Django
# Читаем .env вручную, так как decouple ещё не загружен
_env_file = os.path.join(os.path.dirname(__file__), '.env')
_db_engine = 'postgresql'
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith('DB_ENGINE='):
                _db_engine = _line.split('=', 1)[1].strip()
                break

if _db_engine == 'mysql':
    try:
        import pymysql
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'IdealImage_PDJ.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
