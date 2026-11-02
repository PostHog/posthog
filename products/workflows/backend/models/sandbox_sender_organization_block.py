from django.db import models


class SandboxSenderOrganizationBlock(models.Model):
    organization = models.OneToOneField(
        "posthog.Organization", on_delete=models.CASCADE, db_constraint=False, related_name="+"
    )
    reason = models.TextField()
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.organization.name
