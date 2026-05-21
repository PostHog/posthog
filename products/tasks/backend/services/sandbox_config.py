from django.conf import settings

# Production: 6 hours (safety net; workflow inactivity timeout handles cleanup).
# Tests: 15 min so any sandbox orphaned by a crashed test auto-destroys quickly
# instead of burning Modal capacity for hours.
SANDBOX_TTL_SECONDS = 15 * 60 if settings.TEST else 6 * 60 * 60
