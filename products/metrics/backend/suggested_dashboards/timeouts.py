"""How long the suggested dashboards workflows may run. Free of imports, so the API and the workflows can share it."""

from datetime import timedelta

# Covers two attempts of the 10 minute analysis activity, and the generate starts after it.
SUGGEST_TIMEOUT = timedelta(minutes=30)
# Longer than the worst case of the generate workflow's activity timeouts and retries (about 2 hours),
# so that its finish step runs. The discovery sweep fails a generation that stopped without it.
GENERATE_TIMEOUT = timedelta(hours=3)
