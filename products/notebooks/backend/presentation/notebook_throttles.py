from posthog.rate_limit import _UserBucketRateThrottle


# A notebook create costs little alone, but each new notebook can start a paid kernel sandbox, so a
# scripted create loop turns into a sandbox loop. A person or an agent creates a few notebooks an
# hour, so these rates only stop a script.
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
