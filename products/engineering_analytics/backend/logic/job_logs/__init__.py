"""Fetch GitHub Actions failure logs and ship them into the Logs product.

A scheduled coordinator finds recently-failed CI jobs, and a per-job workflow fetches each job's
log from GitHub (under the shared egress limiter) and emits it line-by-line into the Logs product.
"""

from products.engineering_analytics.backend.logic.job_logs.emitter import JobLogsEmitter

__all__ = ["JobLogsEmitter"]
