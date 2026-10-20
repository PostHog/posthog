"""Celery wiring for research desk session briefs, which core's beat schedule registers."""

from ..tasks.briefs import SESSION_BRIEFS_CRONTAB, post_session_briefs

__all__ = ["SESSION_BRIEFS_CRONTAB", "post_session_briefs"]
