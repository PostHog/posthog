# The OTel ``service.name`` the worker emits CI failure logs under, and the value the failure-logs
# read filters on. A mismatch between the two returns no logs for every PR, with no error. This
# module has no dependencies so that the read path does not import the OTel SDK.
CI_LOGS_SERVICE_NAME = "github-ci-logs"
