/**
 * Мобильные улучшения для IdealImage.ru
 */

(function() {
    'use strict';

    // Lazy loading изображений
    function initLazyLoading() {
        const images = document.querySelectorAll('img[data-src]');
        
        if ('IntersectionObserver' in window) {
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src;
                        img.classList.remove('lazy-load');
                        img.classList.add('loaded');
                        imageObserver.unobserve(img);
                    }
                });
            });

            images.forEach(img => {
                img.classList.add('lazy-load');
                imageObserver.observe(img);
            });
        } else {
            // Fallback для старых браузеров
            images.forEach(img => {
                img.src = img.dataset.src;
                img.classList.add('loaded');
            });
        }
    }

    // Улучшение навигации для мобильных
    function initMobileNavigation() {
        const menuButton = document.getElementById('mobileMenuButton');
        const menu = document.getElementById('menu');
        
        if (menuButton && menu) {
            menuButton.addEventListener('click', function(e) {
                e.preventDefault();
                menu.classList.toggle('show');
                this.classList.toggle('active');
            });

            // Закрытие меню при клике вне его
            document.addEventListener('click', function(e) {
                if (!menu.contains(e.target) && !menuButton.contains(e.target)) {
                    menu.classList.remove('show');
                    menuButton.classList.remove('active');
                }
            });
        }
    }

    // Улучшение форм
    function initFormEnhancements() {
        const forms = document.querySelectorAll('form');
        
        forms.forEach(form => {
            // Предотвращение зума на iOS при фокусе на input
            const inputs = form.querySelectorAll('input, textarea, select');
            inputs.forEach(input => {
                if (input.type !== 'range' && input.type !== 'checkbox' && input.type !== 'radio') {
                    input.addEventListener('focus', function() {
                        if (window.innerWidth <= 768) {
                            setTimeout(() => {
                                this.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            }, 300);
                        }
                    });
                }
            });

            // Валидация в реальном времени
            inputs.forEach(input => {
                input.addEventListener('blur', function() {
                    validateField(this);
                });
            });
        });
    }

    // Валидация полей
    function validateField(field) {
        const value = field.value.trim();
        const type = field.type;
        let isValid = true;
        let message = '';

        // Убираем предыдущие сообщения об ошибках
        const existingError = field.parentNode.querySelector('.field-error');
        if (existingError) {
            existingError.remove();
        }

        // Валидация email
        if (type === 'email' && value) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(value)) {
                isValid = false;
                message = 'Введите корректный email адрес';
            }
        }

        // Валидация обязательных полей
        if (field.hasAttribute('required') && !value) {
            isValid = false;
            message = 'Это поле обязательно для заполнения';
        }

        // Валидация длины
        const minLength = field.getAttribute('minlength');
        const maxLength = field.getAttribute('maxlength');
        
        if (minLength && value.length < parseInt(minLength)) {
            isValid = false;
            message = `Минимум ${minLength} символов`;
        }
        
        if (maxLength && value.length > parseInt(maxLength)) {
            isValid = false;
            message = `Максимум ${maxLength} символов`;
        }

        // Отображение ошибки
        if (!isValid) {
            field.classList.add('is-invalid');
            const errorDiv = document.createElement('div');
            errorDiv.className = 'field-error text-danger small mt-1';
            errorDiv.textContent = message;
            field.parentNode.appendChild(errorDiv);
        } else {
            field.classList.remove('is-invalid');
            field.classList.add('is-valid');
        }

        return isValid;
    }

    // Улучшение производительности
    function initPerformanceOptimizations() {
        // Debounce для поиска
        const searchInputs = document.querySelectorAll('input[type="search"], input[name="query"]');
        searchInputs.forEach(input => {
            let timeout;
            input.addEventListener('input', function() {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    // Здесь можно добавить AJAX поиск
                    console.log('Search query:', this.value);
                }, 300);
            });
        });

        // Предзагрузка критических ресурсов
        const criticalImages = document.querySelectorAll('.card-img-top[src]');
        criticalImages.forEach(img => {
            if (img.complete) {
                img.classList.add('loaded');
            } else {
                img.addEventListener('load', function() {
                    this.classList.add('loaded');
                });
            }
        });
    }

    // Улучшение доступности
    function initAccessibility() {
        // Улучшение фокуса для клавиатурной навигации
        const focusableElements = document.querySelectorAll(
            'a[href], button, input, textarea, select, [tabindex]:not([tabindex="-1"])'
        );

        focusableElements.forEach(element => {
            element.addEventListener('focus', function() {
                this.classList.add('focus-visible');
            });

            element.addEventListener('blur', function() {
                this.classList.remove('focus-visible');
            });
        });

        // ARIA labels для интерактивных элементов
        const buttons = document.querySelectorAll('button:not([aria-label])');
        buttons.forEach(button => {
            if (!button.textContent.trim() && !button.querySelector('img, svg')) {
                button.setAttribute('aria-label', 'Кнопка');
            }
        });
    }

    // Анимации для мобильных
    function initMobileAnimations() {
        // Плавная прокрутка
        const links = document.querySelectorAll('a[href^="#"]');
        links.forEach(link => {
            link.addEventListener('click', function(e) {
                const targetId = this.getAttribute('href');
                if (targetId === '#') return;
                
                const target = document.querySelector(targetId);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });

        // Анимация появления карточек
        const cards = document.querySelectorAll('.card');
        if ('IntersectionObserver' in window) {
            const cardObserver = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.style.opacity = '1';
                        entry.target.style.transform = 'translateY(0)';
                    }
                });
            }, { threshold: 0.1 });

            cards.forEach(card => {
                card.style.opacity = '0';
                card.style.transform = 'translateY(20px)';
                card.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
                cardObserver.observe(card);
            });
        }
    }

    // Обработка ошибок сети
    function initNetworkErrorHandling() {
        window.addEventListener('online', function() {
            showNotification('Соединение восстановлено', 'success');
        });

        window.addEventListener('offline', function() {
            showNotification('Нет соединения с интернетом', 'warning');
        });
    }

    // Показ уведомлений
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; max-width: 300px;';
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(notification);

        // Автоматическое скрытие через 5 секунд
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 5000);
    }

    // Инициализация всех функций
    function init() {
        // Проверяем, что DOM загружен
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        initLazyLoading();
        initMobileNavigation();
        initFormEnhancements();
        initPerformanceOptimizations();
        initAccessibility();
        initMobileAnimations();
        initNetworkErrorHandling();

        console.log('Mobile enhancements initialized');
    }

    // Запуск
    init();

})();
