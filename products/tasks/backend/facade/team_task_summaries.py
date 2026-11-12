"""Facade re-export for reading team-readable tasks with their latest run's summary and status."""

from products.tasks.backend.logic.team_task_summaries import TeamTaskSummary, list_team_task_summaries

__all__ = ["TeamTaskSummary", "list_team_task_summaries"]
