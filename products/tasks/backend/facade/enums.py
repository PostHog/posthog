from django.db import models

CHANNEL_WRITE_TYPE_CHOICES: list[str] = ["public", "private"]


class OnboardingResearchOutcome(models.TextChoices):
    SCRAPED = "scraped", "Scraped"
    NOT_CONFIGURED = "not_configured", "Not configured"
    UNREACHABLE = "unreachable", "Unreachable"
    BUSY = "busy", "Busy"
    SKIPPED = "skipped", "Skipped"
