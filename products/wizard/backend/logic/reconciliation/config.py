from datetime import timedelta

RECONCILIATION_BATCH_SIZE = 100
RECONCILIATION_DISPATCH_TIME_BUDGET_SECONDS = 30
# Local runs have no deadline because the CLI owns them. Expire one only after it stops reporting.
LOCAL_RUN_INACTIVITY_TIMEOUT = timedelta(hours=24)
