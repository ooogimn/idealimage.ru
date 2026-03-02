(function () {
    const TRACK_URL = '/advertising/api/track/impression/';
    const tracked = new Set();
    const visible = new Map();

    const getCsrfToken = () => {
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    };

    const sendImpression = async (target, info) => {
        const key = ${info.type}:;
        if (!info.id || tracked.has(key)) return;

        tracked.add(key);

        try {
            await fetch(TRACK_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    ad_type: info.type,
                    ad_id: Number(info.id),
                    viewport_position: info.position,
                    time_visible: Math.round(info.timeVisible)
                }),
                credentials: 'same-origin'
            });
        } catch (error) {
            console.warn('Ad tracker: failed to send impression', error);
            tracked.delete(key);
        } finally {
            visible.delete(target);
        }
    };

    const collectAds = () => {
        const selector = '[data-ad-banner], [data-ad-context], [data-ad-insertion], [data-ad-type]';
        return Array.from(document.querySelectorAll(selector));
    };

    const resolveInfo = (element) => {
        if (!element) return null;
        const type = element.dataset.adType || (element.dataset.adContext ? 'context' : element.dataset.adInsertion ? 'insertion' : 'banner');
        const id = element.dataset.adBanner || element.dataset.adContext || element.dataset.adInsertion;
        return { type, id };
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            const info = resolveInfo(entry.target);
            if (!info || !info.id) return;

            if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
                if (visible.has(entry.target)) return;
                visible.set(entry.target, {
                    info,
                    position: entry.boundingClientRect.top < window.innerHeight * 0.33 ? 'top' : entry.boundingClientRect.top > window.innerHeight * 0.66 ? 'bottom' : 'middle',
                    start: performance.now()
                });

                // РњРёРЅРёРјР°Р»СЊРЅРѕРµ РІСЂРµРјСЏ РІРёРґРёРјРѕСЃС‚Рё РїРµСЂРµРґ РѕС‚РїСЂР°РІРєРѕР№ вЂ” 400 РјСЃ
                setTimeout(() => {
                    const record = visible.get(entry.target);
                    if (!record) return;
                    const timeVisible = performance.now() - record.start;
                    if (timeVisible < 350) return;
                    sendImpression(entry.target, {
                        ...record.info,
                        timeVisible,
                        position: record.position
                    });
                }, 450);
            } else if (visible.has(entry.target)) {
                const record = visible.get(entry.target);
                const timeVisible = performance.now() - record.start;
                sendImpression(entry.target, {
                    ...record.info,
                    timeVisible,
                    position: record.position
                });
            }
        });
    }, { threshold: [0, 0.5, 1] });

    const init = () => {
        collectAds().forEach((element) => observer.observe(element));
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
