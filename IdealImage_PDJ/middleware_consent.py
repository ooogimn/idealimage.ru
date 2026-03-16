import json
from urllib.parse import unquote


class ConsentMiddleware:
    """
    Добавляет в request распарсенные настройки cookie-consent.
    Сервер может использовать это для шаблонных/API ограничений.
    """

    COOKIE_NAME = "idealimage_cookie_consent"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.cookie_consent = self._parse_cookie(request.COOKIES.get(self.COOKIE_NAME))
        request.analytics_consent = bool(request.cookie_consent.get("analytics"))
        request.ads_consent = bool(request.cookie_consent.get("advertising"))
        return self.get_response(request)

    @staticmethod
    def _parse_cookie(raw_value):
        if not raw_value:
            return {}
        try:
            data = json.loads(unquote(raw_value))
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
