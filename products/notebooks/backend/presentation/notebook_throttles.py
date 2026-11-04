from posthog.rate_limit import _UserBucketRateThrottle


# Each new notebook can start a paid kernel sandbox, so these rates stop a scripted create loop.
class NotebookCreateBurstThrottle(_UserBucketRateThrottle):
    scope = "notebook_create_burst"
    rate = "20/minute"


class NotebookCreateSustainedThrottle(_UserBucketRateThrottle):
    scope = "notebook_create_sustained"
    rate = "120/hour"


class NotebookKernelStartBurstThrottle(_UserBucketRateThrottle):
    scope = "notebook_kernel_start_burst"
    rate = "10/minute"


class NotebookKernelStartSustainedThrottle(_UserBucketRateThrottle):
    scope = "notebook_kernel_start_sustained"
    rate = "60/hour"
