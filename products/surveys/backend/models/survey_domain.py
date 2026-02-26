from django.db import models

from posthog.models.utils import UUIDModel


class SurveyDomain(UUIDModel):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, related_name="survey_domain")
    domain = models.CharField(max_length=256, unique=True, db_index=True)
    redirect_url = models.URLField(max_length=512, blank=True, default="")
    proxy_record = models.OneToOneField(
        "posthog.ProxyRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="survey_domain",
    )
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"SurveyDomain({self.domain})"
