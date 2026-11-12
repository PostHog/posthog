"""Fetch the logs of failed GitHub Actions and Depot CI jobs and emit them into the Logs product."""

from products.engineering_analytics.backend.logic.job_logs.emitter import JobLogsEmitter

__all__ = ["JobLogsEmitter"]
