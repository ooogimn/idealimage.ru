(function () {
    const STORAGE_KEY = 'idealimage_cookie_consent_v1';
    const COOKIE_NAME = 'idealimage_cookie_consent';
    const COOKIE_MAX_AGE = 60 * 60 * 24 * 180; // 180 РґРЅРµР№
    const banner = document.getElementById('cookieBanner');
    if (!banner) return;

    const btnAcceptSelected = banner.querySelector('#cookieAcceptSelected');
    const btnAcceptAll = banner.querySelector('#cookieAcceptAll');
    const btnDecline = banner.querySelector('#cookieDeclineOptional');
    const closeBtn = banner.querySelector('.cookie-close-btn');

    const checkboxes = {
        functional: banner.querySelector('#cookieFunctional'),
        analytics: banner.querySelector('#cookieAnalytics'),
        advertising: banner.querySelector('#cookieAdvertising')
    };

    const isSecure = window.location.protocol === 'https:';

    const parseJson = (raw) => {
        if (!raw) return null;
        try {
            return JSON.parse(raw);
        } catch (err) {
            console.warn('Cookie banner: cannot parse JSON', err);
            return null;
        }
    };

    const readLocal = () => parseJson(localStorage.getItem(STORAGE_KEY));

    const writeLocal = (prefs) => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    };

    const readCookie = () => {
        const match = document.cookie.match(new RegExp(${COOKIE_NAME}=([^;]+)));
        if (!match) return null;
        return parseJson(decodeURIComponent(match[1]));
    };

    const writeCookie = (prefs) => {
        let cookie = ${COOKIE_NAME}=; max-age=; path=/; SameSite=Lax;
        if (isSecure) cookie += '; Secure';
        document.cookie = cookie;
    };

    const normalizePrefs = (prefs) => ({
        necessary: true,
        functional: Boolean(prefs.functional),
        analytics: Boolean(prefs.analytics),
        advertising: Boolean(prefs.advertising),
        updatedAt: prefs.updatedAt || new Date().toISOString()
    });

    const applyPreferences = (prefs) => {
        Object.entries(checkboxes).forEach(([key, checkbox]) => {
            if (!checkbox) return;
            checkbox.checked = Boolean(prefs[key]);
        });
    };

    const hideBanner = () => {
        banner.style.display = 'none';
        document.body.classList.remove('cookie-banner-open');
    };

    const showBanner = () => {
        banner.style.display = 'block';
        document.body.classList.add('cookie-banner-open');
    };

    const collectCurrentPreferences = () => ({
        necessary: true,
        functional: Boolean(checkboxes.functional && checkboxes.functional.checked),
        analytics: Boolean(checkboxes.analytics && checkboxes.analytics.checked),
        advertising: Boolean(checkboxes.advertising && checkboxes.advertising.checked)
    });

    const savePreferences = (prefs) => {
        const payload = normalizePrefs({ ...prefs, updatedAt: new Date().toISOString() });
        writeLocal(payload);
        writeCookie(payload);
        document.dispatchEvent(new CustomEvent('idealimage:cookie-consent', { detail: payload }));
    };

    const loadStoredPreferences = () => {
        const local = readLocal();
        if (local) {
            const normalized = normalizePrefs(local);
            writeCookie(normalized);
            return normalized;
        }
        const cookie = readCookie();
        if (cookie) {
            const normalized = normalizePrefs(cookie);
            writeLocal(normalized);
            return normalized;
        }
        return null;
    };

    const handleAcceptAll = () => {
        Object.values(checkboxes).forEach((checkbox) => {
            if (checkbox) checkbox.checked = true;
        });
        const prefs = collectCurrentPreferences();
        savePreferences(prefs);
        hideBanner();
    };

    const handleAcceptSelected = () => {
        const prefs = collectCurrentPreferences();
        savePreferences(prefs);
        hideBanner();
    };

    const handleDeclineOptional = () => {
        Object.values(checkboxes).forEach((checkbox) => {
            if (checkbox) checkbox.checked = false;
        });
        const prefs = collectCurrentPreferences();
        savePreferences(prefs);
        hideBanner();
    };

    const stored = loadStoredPreferences();
    if (stored) {
        applyPreferences(stored);
        savePreferences(stored);
        hideBanner();
    } else {
        setTimeout(showBanner, 800);
    }

    if (btnAcceptSelected) {
        btnAcceptSelected.addEventListener('click', (event) => {
            event.preventDefault();
            handleAcceptSelected();
        });
    }

    if (btnAcceptAll) {
        btnAcceptAll.addEventListener('click', (event) => {
            event.preventDefault();
            handleAcceptAll();
        });
    }

    if (btnDecline) {
        btnDecline.addEventListener('click', (event) => {
            event.preventDefault();
            handleDeclineOptional();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', (event) => {
            event.preventDefault();
            handleDeclineOptional();
        });
    }
})();
