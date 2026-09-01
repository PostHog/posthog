SUBSCRIPTION_SCHEDULER_BUFFER_MINUTES = 5
# Keep newly committed schedules outside the scheduler's current fetch window,
# including schedules with nonzero seconds.
SUBSCRIPTION_MINIMUM_LEAD_MINUTES = SUBSCRIPTION_SCHEDULER_BUFFER_MINUTES + 2
