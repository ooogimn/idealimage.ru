from django.apps import AppConfig
import sys
import subprocess
import os
from pathlib import Path


class AsistentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Asistent'
    verbose_name = 'AI-Ассистент'
    
    celery_worker_process = None
    celery_beat_process = None
    
    def ready(self):
        """Импортируем signals и запускаем Celery при runserver"""
        # Подключаем сигналы для синхронизации расписаний
        import Asistent.signals
        
        # Сигналы модерации загружаются автоматически через ModerationConfig.ready()
        
        # Подключаем мониторинг в РЕАЛЬНОМ ВРЕМЕНИ (всегда!)
        import Asistent.ai_realtime_monitor
     
        # Автозапуск Celery только при runserver (не при миграциях, shell и т.д.)
        # ВРЕМЕННО ОТКЛЮЧЕНО - на VPS используйте systemd сервисы
        if 'runserver' in sys.argv:
            # self.start_celery()  # Раскомментируйте для локальной разработки
            self.start_periodic_monitor()
    
    def start_celery(self):
        """Автоматический запуск Celery Worker и Beat (только для разработки)"""
        # Проверяем что это первый reloader процесс (Django перезапускает дважды)
        if os.environ.get('RUN_MAIN') == 'true':
            return  # Уже запущено в родительском процессе
        
        try:
            from django.conf import settings
            
            # Проверяем что Celery настроен
            if not hasattr(settings, 'CELERY_BROKER_URL'):
                return
            
            # Создаем папку для логов
            log_dir = Path('logs')
            log_dir.mkdir(exist_ok=True)
            
            print('\n' + '='*70)
            print('🚀 АВТОЗАПУСК Celery Worker + Beat')
            print('='*70 + '\n')
            
            # Запуск Celery Worker
            print('  ⚙️ Запуск Celery Worker...')
            worker_log = log_dir / 'celery_worker.log'
            
            AsistentConfig.celery_worker_process = subprocess.Popen(
                [sys.executable, '-m', 'celery', '-A', 'IdealImage_PDJ', 'worker', '-l', 'info'],
                stdout=open(worker_log, 'w', encoding='utf-8'),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
            )
            print(f'     ✅ Worker запущен (PID: {AsistentConfig.celery_worker_process.pid})')
            print(f'     📝 Лог: {worker_log}\n')
            
            # Запуск Celery Beat
            print('  ⚙️ Запуск Celery Beat...')
            beat_log = log_dir / 'celery_beat.log'
            
            AsistentConfig.celery_beat_process = subprocess.Popen(
                [sys.executable, '-m', 'celery', '-A', 'IdealImage_PDJ', 'beat', '-l', 'info'],
                stdout=open(beat_log, 'w', encoding='utf-8'),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
            )
            print(f'     ✅ Beat запущен (PID: {AsistentConfig.celery_beat_process.pid})')
            print(f'     📝 Лог: {beat_log}\n')
            
            print('='*70)
            print('✅ ВСЕ СЕРВИСЫ ЗАПУЩЕНЫ АВТОМАТИЧЕСКИ!')
            print('='*70)
            print('\n  🌐 Web:      http://127.0.0.1:8000')
            print('  👨‍💼 Admin:    http://127.0.0.1:8000/admin/')
            print('  🤖 AI Chat:  http://127.0.0.1:8000/asistent/chat/')
            print('\n  ⚖️ AI AGENT - ГЛАВНЫЙ МОДЕРАТОР: АКТИВЕН')
            print('  🔴 Мониторинг в РЕАЛЬНОМ ВРЕМЕНИ: ВКЛЮЧЕН')
            print('  🔍 Периодический мониторинг: Каждый час (8:00-21:00)')
            print('\n' + '='*70 + '\n')
            
            # Регистрируем cleanup при выходе
            import atexit
            
            def cleanup():
                if AsistentConfig.celery_worker_process and AsistentConfig.celery_worker_process.poll() is None:
                    print('\n  ⏹️ Остановка Celery Worker...')
                    AsistentConfig.celery_worker_process.terminate()
                    print('     ✅ Worker остановлен\n')
                if AsistentConfig.celery_beat_process and AsistentConfig.celery_beat_process.poll() is None:
                    print('\n  ⏹️ Остановка Celery Beat...')
                    AsistentConfig.celery_beat_process.terminate()
                    print('     ✅ Beat остановлен\n')
            
            atexit.register(cleanup)
            
        except Exception as e:
            print(f'\n⚠️ Warning: Не удалось запустить Celery: {e}')
            print('  Вы можете запустить вручную:')
            print('  celery -A IdealImage_PDJ worker -l info')
            print('  celery -A IdealImage_PDJ beat -l info\n')
    
    def start_periodic_monitor(self):
        """Автоматический запуск периодического мониторинга"""
        # Проверяем что это первый reloader процесс
        if os.environ.get('RUN_MAIN') == 'true':
            return
        
        try:
            import threading
            import time
            from django.core import management
            
            def monitor_loop():
                """Фоновый цикл мониторинга (каждый час)"""
                time.sleep(60)  # Подождать 1 минуту после старта
                
                while True:
                    try:
                        # Проверяем время (только 8:00-21:00)
                        from django.utils import timezone
                        current_hour = timezone.now().hour
                        
                        if 8 <= current_hour < 21:
                            print(f'\n🔍 [{timezone.now().strftime("%H:%M")}] AI Agent автомониторинг...')
                            management.call_command('ai_auto_monitor')
                            print(f'✅ Мониторинг завершён\n')
                        
                        # Ждём 1 час
                        time.sleep(3600)
                        
                    except Exception as e:
                        print(f'⚠️ Ошибка автомониторинга: {e}')
                        time.sleep(3600)
            
            # Запускаем в отдельном потоке
            monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
            monitor_thread.start()
            
            print('  🔍 Автоматический мониторинг: ВКЛЮЧЕН (каждый час 8:00-21:00)')
            
            # Запускаем очистку базы данных при старте
            self.cleanup_database_on_start()
            
        except Exception as e:
            print(f'\n⚠️ Warning: Не удалось запустить автомониторинг: {e}')
            print('  Настройте через cron или Планировщик Windows\n')
    
    def cleanup_database_on_start(self):
        """Очистка базы данных при запуске сервера"""
        try:
            import threading
            from django.core import management
            
            def cleanup():
                """Очистка базы данных в отдельном потоке"""
                import time
                time.sleep(5)  # Ждём полной инициализации Django
                
                try:
                    from Asistent.moderations.signals import ai_agent_cleanup_database
                    
                    print('\n🗑️ AI Agent проверяет базу данных...')
                    result = ai_agent_cleanup_database()
                    
                    if result:
                        total_deleted = result['deleted_no_image'] + result['deleted_broken_image']
                        total_fixed = result['changed_to_draft']
                        
                        if total_deleted > 0 or total_fixed > 0:
                            print(f'  ❌ Удалено проблемных статей: {total_deleted}')
                            print(f'  📝 Переведено в черновики: {total_fixed}')
                            print('  ✅ База данных очищена!')
                        else:
                            print('  ✅ Проблем не найдено')
                    
                    print('')
                    
                except Exception as e:
                    print(f'  ⚠️ Ошибка очистки: {e}\n')
            
            cleanup_thread = threading.Thread(target=cleanup, daemon=True)
            cleanup_thread.start()
            
            print('  🗑️ Автоматическая очистка БД: ВКЛЮЧЕНА (при старте)')
            
        except Exception as e:
            print(f'\n⚠️ Warning: Не удалось запустить очистку БД: {e}\n')
