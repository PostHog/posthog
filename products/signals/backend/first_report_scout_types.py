from typing import Literal

from django.db import models

from pydantic import BaseModel, Field


class FirstReportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    NO_DATA = "no_data", "No data"
    REPORT_CREATED = "report_created", "Report created"
    INSUFFICIENT_DATA = "insufficient_data", "Insufficient data"
    NO_ACTIONABLE_FINDING = "no_actionable_finding", "No actionable finding"
    INCOMPLETE = "incomplete", "Incomplete"


class FirstReportScoutResult(BaseModel):
    outcome: Literal["report_created", "insufficient_data", "no_actionable_finding", "incomplete"]
    checked_products: list[str] = Field(default_factory=list, max_length=30)
    missing_data: list[str] = Field(default_factory=list, max_length=10)
