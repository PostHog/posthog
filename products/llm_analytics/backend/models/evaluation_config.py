from django.db import models


class EvaluationConfig(models.Model):
    """Team-level configuration and usage tracking for LLM evaluations"""

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="evaluation_config",
    )

    # Trial evaluations (permanent limit for alpha)
    trial_eval_limit = models.IntegerField(default=100)
    trial_evals_used = models.IntegerField(default=0)

    # Active BYOK key (single source of truth)
    active_provider_key = models.ForeignKey(
        "llm_analytics.LLMProviderKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "llm_analytics"

    def __str__(self):
        return f"EvaluationConfig for team {self.team_id}"

    @property
    def trial_evals_remaining(self) -> int:
        return max(0, self.trial_eval_limit - self.trial_evals_used)

    @property
    def trial_limit_reached(self) -> bool:
        return self.trial_evals_used >= self.trial_eval_limit
