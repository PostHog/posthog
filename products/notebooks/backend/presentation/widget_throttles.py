from rest_framework.request import Request
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView


class _WidgetFrameThrottle(UserRateThrottle):
    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        user_id = getattr(request.user, "pk", None)
        if user_id is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user_id}


class WidgetFrameBurstThrottle(_WidgetFrameThrottle):
    scope = "notebook_widget_frame_burst"
    rate = "120/minute"


class WidgetFrameSustainedThrottle(_WidgetFrameThrottle):
    scope = "notebook_widget_frame_sustained"
    rate = "1200/hour"
