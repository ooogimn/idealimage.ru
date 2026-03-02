/**
 * Система лайков и реакций для IdealImage.ru
 */

(function() {
    'use strict';

    class LikesSystem {
        constructor() {
            this.init();
        }

        init() {
            this.bindEvents();
            this.loadInitialStats();
        }

        bindEvents() {
            // Обработчики для кнопок лайков
            document.addEventListener('click', (e) => {
                if (e.target.matches('[data-like-btn]') || e.target.closest('[data-like-btn]')) {
                    e.preventDefault();
                    const button = e.target.matches('[data-like-btn]') ? e.target : e.target.closest('[data-like-btn]');
                    this.handleLike(button);
                }

                // Обработчики для рейтинга
                if (e.target.matches('[data-rating-star]') || e.target.closest('[data-rating-star]')) {
                    e.preventDefault();
                    const star = e.target.matches('[data-rating-star]') ? e.target : e.target.closest('[data-rating-star]');
                    this.handleRating(star);
                }

                // Обработчики для закладок
                if (e.target.matches('[data-bookmark-btn]') || e.target.closest('[data-bookmark-btn]')) {
                    e.preventDefault();
                    const button = e.target.matches('[data-bookmark-btn]') ? e.target : e.target.closest('[data-bookmark-btn]');
                    this.handleBookmark(button);
                }
            });
        }

        async handleLike(button) {
            const postId = button.dataset.postId;
            const reactionType = button.dataset.reactionType || 'like';

            if (!postId) {
                console.error('Post ID not found');
                return;
            }

            try {
                button.disabled = true;
                button.classList.add('loading');

                const response = await fetch(`/blog/api/post/${postId}/like/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCSRFToken()
                    },
                    body: JSON.stringify({
                        reaction_type: reactionType
                    })
                });

                const data = await response.json();

                if (data.success) {
                    this.updateLikeUI(button, data);
                    this.showNotification(this.getReactionMessage(data.action, reactionType), 'success');
                } else {
                    this.showNotification(data.error || 'Ошибка при обработке лайка', 'error');
                }
            } catch (error) {
                console.error('Error:', error);
                this.showNotification('Ошибка соединения', 'error');
            } finally {
                button.disabled = false;
                button.classList.remove('loading');
            }
        }

        async handleRating(star) {
            const postId = star.dataset.postId;
            const rating = parseInt(star.dataset.rating);

            if (!postId || !rating) {
                console.error('Post ID or rating not found');
                return;
            }

            try {
                const response = await fetch(`/blog/api/post/${postId}/rate/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCSRFToken()
                    },
                    body: JSON.stringify({
                        rating: rating
                    })
                });

                const data = await response.json();

                if (data.success) {
                    this.updateRatingUI(star, data);
                    this.showNotification(`Оценка ${rating}/5 сохранена`, 'success');
                } else {
                    this.showNotification(data.error || 'Ошибка при сохранении оценки', 'error');
                }
            } catch (error) {
                console.error('Error:', error);
                this.showNotification('Ошибка соединения', 'error');
            }
        }

        async handleBookmark(button) {
            const postId = button.dataset.postId;

            if (!postId) {
                console.error('Post ID not found');
                return;
            }

            try {
                button.disabled = true;
                button.classList.add('loading');

                const response = await fetch(`/blog/api/post/${postId}/bookmark/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCSRFToken()
                    }
                });

                const data = await response.json();

                if (data.success) {
                    this.updateBookmarkUI(button, data);
                    const message = data.action === 'added' ? 'Добавлено в закладки' : 'Удалено из закладок';
                    this.showNotification(message, 'success');
                } else {
                    this.showNotification(data.error || 'Ошибка при работе с закладками', 'error');
                }
            } catch (error) {
                console.error('Error:', error);
                this.showNotification('Ошибка соединения', 'error');
            } finally {
                button.disabled = false;
                button.classList.remove('loading');
            }
        }

        updateLikeUI(button, data) {
            const postId = button.dataset.postId;
            const reactionType = button.dataset.reactionType || 'like';

            // Обновляем кнопку
            if (data.user_reaction === reactionType) {
                button.classList.add('active');
                button.setAttribute('aria-pressed', 'true');
            } else {
                button.classList.remove('active');
                button.setAttribute('aria-pressed', 'false');
            }

            // Обновляем счетчики
            this.updateLikeCounters(postId, data);
        }

        updateLikeCounters(postId, data) {
            // Общий счетчик лайков
            const totalCounter = document.querySelector(`[data-likes-total="${postId}"]`);
            if (totalCounter) {
                totalCounter.textContent = data.likes_count;
            }

            // Счетчики по типам реакций
            data.likes_by_type.forEach(item => {
                const counter = document.querySelector(`[data-likes-type="${item.reaction_type}"][data-post-id="${postId}"]`);
                if (counter) {
                    counter.textContent = item.count;
                }
            });

            // Обновляем все кнопки реакций для этого поста
            const reactionButtons = document.querySelectorAll(`[data-like-btn][data-post-id="${postId}"]`);
            reactionButtons.forEach(btn => {
                const btnReactionType = btn.dataset.reactionType;
                if (data.user_reaction === btnReactionType) {
                    btn.classList.add('active');
                    btn.setAttribute('aria-pressed', 'true');
                } else {
                    btn.classList.remove('active');
                    btn.setAttribute('aria-pressed', 'false');
                }
            });
        }

        updateRatingUI(star, data) {
            const postId = star.dataset.postId;

            // Обновляем звезды
            const stars = document.querySelectorAll(`[data-rating-star][data-post-id="${postId}"]`);
            stars.forEach(s => {
                const starRating = parseInt(s.dataset.rating);
                if (starRating <= data.user_rating) {
                    s.classList.add('active');
                } else {
                    s.classList.remove('active');
                }
            });

            // Обновляем счетчики рейтинга
            const avgRating = document.querySelector(`[data-rating-avg="${postId}"]`);
            if (avgRating) {
                avgRating.textContent = data.average_rating;
            }

            const ratingsCount = document.querySelector(`[data-rating-count="${postId}"]`);
            if (ratingsCount) {
                ratingsCount.textContent = data.ratings_count;
            }
        }

        updateBookmarkUI(button, data) {
            const postId = button.dataset.postId;

            // Обновляем кнопку закладки
            if (data.is_bookmarked) {
                button.classList.add('active');
                button.setAttribute('aria-pressed', 'true');
            } else {
                button.classList.remove('active');
                button.setAttribute('aria-pressed', 'false');
            }

            // Обновляем счетчик закладок
            const counter = document.querySelector(`[data-bookmarks-count="${postId}"]`);
            if (counter) {
                counter.textContent = data.bookmarks_count;
            }
        }

        async loadInitialStats() {
            // Загружаем начальную статистику для всех постов на странице
            const postElements = document.querySelectorAll('[data-post-id]');
            const postIds = [...new Set(Array.from(postElements).map(el => el.dataset.postId))];

            for (const postId of postIds) {
                try {
                    const response = await fetch(`/blog/api/post/${postId}/stats/`);
                    const data = await response.json();

                    if (data.success) {
                        this.updateLikeCounters(postId, data.likes);
                        this.updateRatingUI({ dataset: { postId } }, data.ratings);
                        this.updateBookmarkUI({ dataset: { postId } }, data.bookmarks);
                    }
                } catch (error) {
                    console.error(`Error loading stats for post ${postId}:`, error);
                }
            }
        }

        getReactionMessage(action, reactionType) {
            const reactions = {
                'like': '👍',
                'love': '❤️',
                'laugh': '😂',
                'wow': '😮',
                'sad': '😢',
                'angry': '😠'
            };

            const emoji = reactions[reactionType] || '👍';
            
            switch (action) {
                case 'added':
                    return `${emoji} Реакция добавлена`;
                case 'updated':
                    return `${emoji} Реакция изменена`;
                case 'removed':
                    return 'Реакция удалена';
                default:
                    return 'Реакция обновлена';
            }
        }

        getCSRFToken() {
            const token = document.querySelector('[name=csrfmiddlewaretoken]');
            return token ? token.value : '';
        }

        showNotification(message, type = 'info') {
            // Создаем уведомление
            const notification = document.createElement('div');
            notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
            notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; max-width: 300px;';
            notification.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

            document.body.appendChild(notification);

            // Автоматическое скрытие через 3 секунды
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 3000);
        }
    }

    // Инициализация при загрузке DOM
    document.addEventListener('DOMContentLoaded', () => {
        new LikesSystem();
    });

})();
