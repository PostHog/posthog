from posthog.rate_limit import _UserBucketRateThrottle


class WidgetFrameBurstThrottle(_UserBucketRateThrottle):
    scope = "notebook_widget_frame_burst"
    rate = "120/minute"


class WidgetFrameSustainedThrottle(_UserBucketRateThrottle):
    scope = "notebook_widget_frame_sustained"
    rate = "1200/hour"
