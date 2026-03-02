/**
 * Общие функции для админских дашбордов IdealImage.ru
 */

// Получить CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCookie('csrftoken');

// AJAX запрос с обработкой ошибок
async function apiRequest(url, method = 'GET', data = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken
        }
    };
    
    if (data && method !== 'GET') {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(url, options);
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || 'Ошибка запроса');
        }
        
        return result;
    } catch (error) {
        console.error('API Error:', error);
        showNotification('Ошибка: ' + error.message, 'error');
        throw error;
    }
}

// Показать уведомление
function showNotification(message, type = 'success') {
    // Создаем контейнер для уведомлений если его нет
    let container = document.getElementById('notifications-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notifications-container';
        container.className = 'fixed top-4 right-4 z-50 space-y-2';
        document.body.appendChild(container);
    }
    
    // Создаем уведомление
    const notification = document.createElement('div');
    notification.className = `px-6 py-4 rounded-lg shadow-lg transform transition-all duration-300 ${
        type === 'success' ? 'bg-green-500' :
        type === 'error' ? 'bg-red-500' :
        type === 'warning' ? 'bg-yellow-500' :
        'bg-blue-500'
    } text-white max-w-md`;
    notification.innerHTML = `
        <div class="flex items-center justify-between">
            <span>${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-4 text-white hover:text-gray-200">
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                </svg>
            </button>
        </div>
    `;
    
    container.appendChild(notification);
    
    // Автоматическое удаление через 5 секунд
    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 300);
    }, 5000);
}

// Функции для работы с бонусами

// Получить статистику автора
async function getAuthorStats(authorId, period = 'week') {
    try {
        const result = await apiRequest(`/donations/api/author-stats/${authorId}/?period=${period}`);
        return result.stats;
    } catch (error) {
        console.error('Error getting author stats:', error);
        return null;
    }
}

// Предварительный расчет бонуса
async function calculateBonusPreview(authorId) {
    try {
        const result = await apiRequest('/donations/api/calculate-preview/', 'POST', { author_id: authorId });
        return result.preview;
    } catch (error) {
        console.error('Error calculating bonus preview:', error);
        return null;
    }
}

// Отметить выплату
async function markPaymentAsPaid(registryId, paidAmount, paymentMethod, paymentNote) {
    try {
        const result = await apiRequest('/donations/api/mark-payment/', 'POST', {
            registry_id: registryId,
            paid_amount: paidAmount,
            payment_method: paymentMethod,
            payment_note: paymentNote
        });
        
        showNotification(result.message, 'success');
        return result;
    } catch (error) {
        return null;
    }
}

// Добавить штраф или премию
async function addPenaltyReward(authorId, type, amount, amountType, reason, appliedTo) {
    try {
        const result = await apiRequest('/donations/api/add-penalty-reward/', 'POST', {
            author_id: authorId,
            type: type,
            amount: amount,
            amount_type: amountType,
            reason: reason,
            applied_to: appliedTo
        });
        
        showNotification(result.message, 'success');
        return result;
    } catch (error) {
        return null;
    }
}

// Обновить формулу
async function updateFormula(roleId, formulaData) {
    try {
        const data = { role_id: roleId, ...formulaData };
        const result = await apiRequest('/donations/api/update-formula/', 'POST', data);
        
        showNotification(result.message, 'success');
        return result;
    } catch (error) {
        return null;
    }
}

// Сгенерировать отчет
async function generateWeeklyReport() {
    if (!confirm('Сгенерировать отчет за прошлую неделю?')) {
        return;
    }
    
    try {
        const result = await apiRequest('/donations/api/generate-report/', 'POST');
        showNotification(result.message, 'success');
        
        // Перезагрузить страницу через 2 секунды
        setTimeout(() => location.reload(), 2000);
        
        return result;
    } catch (error) {
        return null;
    }
}

// Показать детальную статистику автора
async function showAuthorDetails(authorId) {
    try {
        const result = await apiRequest(`/donations/api/author-detail/${authorId}/`);
        
        // Создаем модальное окно
        const modal = createAuthorDetailsModal(result);
        document.body.appendChild(modal);
        
    } catch (error) {
        console.error('Error showing author details:', error);
    }
}

// Создать модальное окно с детальной статистикой
function createAuthorDetailsModal(data) {
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.onclick = (e) => {
        if (e.target === modal) modal.remove();
    };
    
    modal.innerHTML = `
        <div class="bg-white dark:bg-gray-800 rounded-2xl p-8 max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div class="flex justify-between items-start mb-6">
                <div>
                    <h2 class="text-2xl font-bold text-gray-900 dark:text-white">${data.author.full_name}</h2>
                    <p class="text-gray-600 dark:text-gray-400">@${data.author.username}</p>
                </div>
                <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                    <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                    </svg>
                </button>
            </div>
            
            ${data.week_stats.exists ? `
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                    <div class="text-center p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                        <p class="text-sm text-gray-600 dark:text-gray-400">Статьи</p>
                        <p class="text-3xl font-bold text-blue-600">${data.week_stats.articles_count}</p>
                    </div>
                    <div class="text-center p-4 bg-pink-50 dark:bg-pink-900/20 rounded-lg">
                        <p class="text-sm text-gray-600 dark:text-gray-400">Лайки</p>
                        <p class="text-3xl font-bold text-pink-600">${data.week_stats.total_likes}</p>
                    </div>
                    <div class="text-center p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
                        <p class="text-sm text-gray-600 dark:text-gray-400">Комментарии</p>
                        <p class="text-3xl font-bold text-green-600">${data.week_stats.total_comments}</p>
                    </div>
                    <div class="text-center p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg">
                        <p class="text-sm text-gray-600 dark:text-gray-400">Просмотры</p>
                        <p class="text-3xl font-bold text-purple-600">${data.week_stats.total_views}</p>
                    </div>
                </div>
                
                ${data.latest_bonus ? `
                    <div class="bg-green-50 dark:bg-green-900/20 rounded-lg p-6">
                        <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">Последний бонус</p>
                        <p class="text-4xl font-bold text-green-600 mb-2">${data.latest_bonus.total}₽</p>
                        <p class="text-sm text-gray-600 dark:text-gray-400">${data.latest_bonus.status} | ${data.latest_bonus.period}</p>
                    </div>
                ` : '<p class="text-gray-500 text-center py-4">Нет данных о бонусах</p>'}
            ` : '<p class="text-gray-500 text-center py-8">Статистика не рассчитана</p>'}
        </div>
    `;
    
    return modal;
}

// Утилиты для форматирования
function formatCurrency(amount) {
    return new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        minimumFractionDigits: 2
    }).format(amount);
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU');
}

function formatDateTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ru-RU');
}

// Экспорт функций для глобального использования
window.Dashboard = {
    getAuthorStats,
    calculateBonusPreview,
    markPaymentAsPaid,
    addPenaltyReward,
    updateFormula,
    generateWeeklyReport,
    showAuthorDetails,
    showNotification,
    formatCurrency,
    formatDate,
    formatDateTime
};

