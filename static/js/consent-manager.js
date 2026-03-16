(function () {
    var CONSENT_COOKIE = "idealimage_cookie_consent";
    var executedCategories = {
        analytics: false,
        ads: false
    };

    function parseJSON(value) {
        if (!value) return null;
        try {
            return JSON.parse(value);
        } catch (err) {
            return null;
        }
    }

    function getConsent() {
        var match = document.cookie.match(new RegExp(CONSENT_COOKIE + "=([^;]+)"));
        if (!match) return null;
        return parseJSON(decodeURIComponent(match[1]));
    }

    function loadScript(src, attrs) {
        var script = document.createElement("script");
        script.src = src;
        script.async = true;
        if (attrs) {
            Object.keys(attrs).forEach(function (key) {
                script.setAttribute(key, attrs[key]);
            });
        }
        document.head.appendChild(script);
        return script;
    }

    function executeDeferredScripts(category) {
        var selector = 'script[type="text/plain"][data-consent="' + category + '"]';
        document.querySelectorAll(selector).forEach(function (sourceNode) {
            if (sourceNode.dataset.executed === "1") return;
            var script = document.createElement("script");
            if (sourceNode.src) {
                script.src = sourceNode.src;
                script.async = true;
            } else {
                script.textContent = sourceNode.textContent;
            }
            sourceNode.dataset.executed = "1";
            document.head.appendChild(script);
        });
    }

    function grantAnalytics(config) {
        if (executedCategories.analytics) return;
        executedCategories.analytics = true;

        window.dataLayer = window.dataLayer || [];
        window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
        window.gtag("consent", "default", {
            ad_storage: "denied",
            analytics_storage: "denied",
            ad_user_data: "denied",
            ad_personalization: "denied"
        });
        window.gtag("consent", "update", {
            ad_storage: "granted",
            analytics_storage: "granted",
            ad_user_data: "granted",
            ad_personalization: "granted"
        });
        window.gtag("js", new Date());
        window.gtag("config", config.gaMeasurementId);

        loadScript(
            "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(config.gaMeasurementId),
            { "data-consent": "analytics", "data-idealimage": "ga4" }
        );

        window.ym = window.ym || function () {
            (window.ym.a = window.ym.a || []).push(arguments);
        };
        window.ym.l = 1 * new Date();
        loadScript(
            "https://mc.yandex.ru/metrika/tag.js",
            { "data-consent": "analytics", "data-idealimage": "yandex-metrika" }
        );
        window.ym(config.yandexMetrikaId, "init", {
            clickmap: true,
            accurateTrackBounce: true,
            trackLinks: true,
            webvisor: true,
            ecommerce: "dataLayer"
        });

        executeDeferredScripts("analytics");
        window.dispatchEvent(new CustomEvent("consentGranted", { detail: { category: "analytics" } }));
    }

    function grantAds() {
        if (executedCategories.ads) return;
        executedCategories.ads = true;
        executeDeferredScripts("ads");
        window.dispatchEvent(new CustomEvent("consentGranted", { detail: { category: "ads" } }));
    }

    function applyConsent(consent) {
        var configNode = document.getElementById("consent-config");
        var config = parseJSON(configNode ? configNode.textContent : "") || {};
        if (!config.gaMeasurementId || !config.yandexMetrikaId) return;

        window.idealimageAnalyticsAllowed = function () {
            return Boolean(consent && consent.analytics);
        };

        if (consent && consent.analytics) {
            grantAnalytics(config);
        }
        if (consent && consent.advertising) {
            grantAds();
        }
    }

    document.addEventListener("idealimage:cookie-consent", function (event) {
        applyConsent(event.detail || getConsent());
    });

    applyConsent(getConsent());
})();
