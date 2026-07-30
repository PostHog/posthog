from django.conf import settings

# Production: 6 hours (safety net; workflow inactivity timeout handles cleanup).
# Tests: 15 min so any sandbox orphaned by a crashed test auto-destroys quickly
# instead of burning Modal capacity for hours.
SANDBOX_TTL_SECONDS = 15 * 60 if settings.TEST else 6 * 60 * 60

# Default request floor for burstable sandboxes (used when SandboxConfig.burstable_resources is
# True): the box reserves only this much and bursts up to its configured cpu_cores / memory_gb.
# Modal bills max(request, actual), so an idle burstable box costs the floor, not the full size.
BURSTABLE_REQUEST_CPU_CORES = 0.5
BURSTABLE_REQUEST_MEMORY_MB = 1024

VM_SANDBOX_CPU_CORES = 8.0

# Upper bounds for per-task sandbox resource overrides. Override values are clamped
# to these so a bad or hostile value can't provision an oversized/long-lived sandbox.
MAX_SANDBOX_CPU_CORES = 16
MAX_SANDBOX_MEMORY_GB = 64
MAX_SANDBOX_TTL_SECONDS = SANDBOX_TTL_SECONDS
