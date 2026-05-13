"""Django models for githog."""

from django.db import models


class GitHogConversationMessage(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    repository = models.CharField(max_length=512, help_text="Repository in owner/name format.")
    pull_request_number = models.IntegerField()
    author = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
