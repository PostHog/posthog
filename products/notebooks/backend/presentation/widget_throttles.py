from typing import TYPE_CHECKING

from posthog.rate_limit import _UserBucketRateThrottle

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class WidgetSnapshotThrottle(_UserBucketRateThrottle):
    scope = "notebook_widget_snapshot"
    rate = "10/hour"


class WidgetSnapshotPublishThrottle(WidgetSnapshotThrottle):
    def allow_request(self, request: "Request", view: "APIView") -> bool:
        if isinstance(request.data, dict) and request.data.get("tile_id") is not None:
            self.scope = "notebook_widget_snapshot_refresh"
            self.rate = "60/hour"
            self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class WidgetFrameBurstThrottle(_UserBucketRateThrottle):
    scope = "notebook_widget_frame_burst"
    rate = "120/minute"


class WidgetFrameSustainedThrottle(_UserBucketRateThrottle):
    scope = "notebook_widget_frame_sustained"
    rate = "1200/hour"
