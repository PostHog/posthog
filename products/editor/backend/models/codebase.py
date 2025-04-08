from django.db import models

from posthog.models.utils import UUIDModel


class Codebase(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="editor_codebases")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="editor_codebases")
