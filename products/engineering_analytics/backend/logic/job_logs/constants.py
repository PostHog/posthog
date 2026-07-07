# Shared between the emit and read sides of the CI job-logs feature.

# The OTel ``service.name`` the worker emits CI failure logs under, and the value the failure-logs
# read query (`ci_failure_logs`) filters on. Kept here — not imported across the two sides — so a
# rename can't silently desync them: a mismatch returns no logs (`logs_available: false`) for every
# PR, with no error. Defined in a dependency-free module so the read path doesn't pull the OTel SDK.
CI_LOGS_SERVICE_NAME = "github-ci-logs"
