# -*- coding: utf-8 -*-
import re

file_path = 'f:/PROGER/SAITS_MAY/SERVERA/IDEALIMAGE/idealimage.ru/templates/home/index.html'

with open(file_path, 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Секция AI-технологий
html = re.sub(r'<!-- Unique Content & AI Technology Section.*?<!-- Popular Categories Section -->', '<!-- Popular Categories Section -->', html, flags=re.DOTALL)

# 2. Секция для авторов (Станьте блогером)
html = re.sub(r'<!-- Become a Blogger Section -->.*?<!-- 🏆 Топ популярных статей -->', '<!-- 🏆 Топ популярных статей -->', html, flags=re.DOTALL)        

# 3. Блок для рекламодателей -> Секция Контакты
contacts_section = """<!-- Секция Контакты -->
<section id="contacts-section" class="py-6 md:py-16 relative overflow-hidden text-white min-h-[15vh] md:min-h-[55vh]">
    <div class="absolute inset-0 bg-gradient-to-br from-indigo-600 via-purple-600 to-pink-600 opacity-90">
        <div class="absolute inset-0" style="background-image: radial-gradient(circle, rgba(255,255,255,0.1) 1px, transparent 1px); background-size: 50px 50px;"></div>
    </div>
    <div class="max-w-7xl mx-auto px-4 relative z-10">
        <div class="text-center mb-16">
            <h2 class="text-4xl md:text-5xl font-heading font-bold text-white mb-4">
                Сотрудничество и реклама
            </h2>
            <p class="text-xl text-white/90 max-w-3xl mx-auto">
                Мы открыты для новых проектов, партнерства и ответим на любые вопросы по размещению рекламы
            </p>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 mb-12">
            <!-- Email -->
            <div class="bg-white/10 backdrop-blur-md rounded-2xl p-8 hover:bg-white/20 transition-all flex flex-col items-center text-center">
                <div class="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center mb-6">
                    <span class="text-3xl">📧</span>
                </div>
                <h3 class="text-2xl font-bold mb-3">Email</h3>
                <p class="text-white/80 mb-4 flex-1">Для официальных запросов, предложений и сотрудничества</p>
                <a href="mailto:info@idealimage.ru" class="text-lg font-semibold hover:text-white transition-colors border-b border-transparent hover:border-white">
                    info@idealimage.ru
                </a>
            </div>
            
            <!-- Telegram -->
            <div class="bg-white/10 backdrop-blur-md rounded-2xl p-8 hover:bg-white/20 transition-all flex flex-col items-center text-center">
                <div class="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center mb-6">
                    <span class="text-3xl">📱</span>
                </div>
                <h3 class="text-2xl font-bold mb-3">Telegram</h3>
                <p class="text-white/80 mb-4 flex-1">Для быстрой связи, обсуждения размещения рекламы</p>
                <a href="https://t.me/idealimage_admin" target="_blank" rel="noopener noreferrer" class="text-lg font-semibold hover:text-white transition-colors border-b border-transparent hover:border-white">
                    @idealimage_admin
                </a>
            </div>
            
            <!-- Форма или Рекламодателям -->
            <div class="bg-white/10 backdrop-blur-md rounded-2xl p-8 hover:bg-white/20 transition-all flex flex-col items-center text-center">
                <div class="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center mb-6">
                    <span class="text-3xl">💡</span>
                </div>
                <h3 class="text-2xl font-bold mb-3">Рекламодателям</h3>
                <p class="text-white/80 mb-4 flex-1">Ознакомьтесь с условиями размещения рекламы на нашем сайте</p>
                <a href="{% url 'Home:advertising' %}" class="inline-flex items-center px-6 py-3 bg-white text-primary font-bold rounded-lg shadow-lg hover:shadow-xl transform hover:-translate-y-1 transition-all">
                    Условия рекламы
                </a>
            </div>
        </div>
    </div>
</section>
"""

html = re.sub(r'<!-- \S+ Реклама на нашем сайте.*?<!-- Целая сеть порталов -->', contacts_section + '\n\n<!-- Целая сеть порталов -->', html, flags=re.DOTALL)

# Пробуем другой вариант, в случае если эмодзи в регулярке не обработалось
if '<!-- Секция Контакты -->' not in html:
    html = re.sub(r'<section class="py-6 md:py-16 relative overflow-hidden text-white min-h-\[15vh\] md:min-h-\[55vh\]">\s*{% include \'home/partials/section_background.html\' with bg=sections_backgrounds.advertising.*?<!-- Целая сеть порталов -->', contacts_section + '\n\n<!-- Целая сеть порталов -->', html, flags=re.DOTALL)

# 4. Текст про здоровье
old_text = 'Уникальный контент о моде, красоте и здоровье с модерацией и продвижением от искусственного интеллекта'
new_text = 'Авторский контент о моде, красоте и стиле жизни'
html = html.replace(old_text, new_text)

# Убираем старую live-stat, если она тоже не в тему, хотя ее вроде просили оставить. 
# "с модерацией и продвижением от искусственного интеллекта" нужно было выпилить. Я использую replace.

# 5. Кнопки aria-label
html = html.replace('<button id="carousel-prev"', '<button id="carousel-prev" aria-label="Предыдущие статьи"')
html = html.replace('<button id="carousel-next"', '<button id="carousel-next" aria-label="Следующие статьи"')

# 6. initBackgroundVideos => using IntersectionObserver
old_bg_videos = r'// Auto-play background videos.*?(?=// Top Posts Carousel -)'
new_bg_videos = """// Auto-play background videos (IntersectionObserver)
function initBackgroundVideos() {
    const videos = document.querySelectorAll('video[autoplay]');
    
    if ('IntersectionObserver' in window) {
        const videoObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.play().catch(e => console.log('Autoplay prevented:', e));
                } else {
                    entry.target.pause();
                }
            });
        });
        videos.forEach(v => {
            videoObserver.observe(v);
            v.addEventListener('ended', function() { this.currentTime = 0; this.play(); });
        });
    } else {
        videos.forEach(v => {
            v.play().catch(e => console.log('Autoplay prevented:', e));
            v.addEventListener('ended', function() { this.currentTime = 0; this.play(); });
        });
    }
}

"""
html = re.sub(old_bg_videos, new_bg_videos, html, flags=re.DOTALL)

# 7. Калькулятор - удалить
html = re.sub(r'// Earnings Calculator Script.*?function calculateEarnings\(\) \{.*?(?=\s*// Auto-play background videos)', '', html, flags=re.DOTALL)
html = html.replace('calculateEarnings();\n    ', '')
html = html.replace('calculateEarnings();', '')

html = html.replace('<!-- Earnings Calculator Script -->\n<script>', '<script>')

# 8. Schema.org
jsonld = """
<!-- Schema.org WebSite -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "IdealImage.ru",
  "url": "https://idealimage.ru/",
  "potentialAction": {
    "@type": "SearchAction",
    "target": "https://idealimage.ru/search/?query={search_term_string}",
    "query-input": "required name=search_term_string"
  }
}
</script>
"""

if "<!-- Schema.org WebSite -->" not in html:
    html = html.replace('{% endblock %}', jsonld + '\n{% endblock %}')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("HTML template successfully updated!")
