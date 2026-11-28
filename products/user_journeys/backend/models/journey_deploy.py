"""A deploy that CI announced, and the journey runs it started against the new build.

The row is also the marker that conversion is compared across, so it exists whether or not any run
started.
"""

from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.user_journeys.backend.facade.contracts import (
    MAX_BRANCH_LENGTH,
    MAX_COMMIT_SHA_LENGTH,
    MAX_DEPLOY_LABEL_LENGTH,
    MAX_URL_LENGTH,
)


class JourneyDeploy(TeamScopedRootMixin, UUIDModel):
    # No database constraint: creating one takes a lock on `posthog_team` that queues behind
    # live writes. Django still cascades the delete in Python.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # No database constraint, for the same reason on `posthog_user`. Null for a project secret API key.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deployed_at = models.DateTimeField(default=timezone.now)

    commit_sha = models.CharField(max_length=MAX_COMMIT_SHA_LENGTH)
    branch = models.CharField(max_length=MAX_BRANCH_LENGTH, null=True, blank=True)
    # The origin of the build under test. Null means each journey opens its own start URL.
    base_url = models.CharField(max_length=MAX_URL_LENGTH, null=True, blank=True)
    label = models.CharField(max_length=MAX_DEPLOY_LABEL_LENGTH, null=True, blank=True)
    url = models.CharField(max_length=MAX_URL_LENGTH, null=True, blank=True)
    # The `JourneyDeploySkip` contract list, written once when the deploy starts its runs.
    skipped = models.JSONField(default=list)
    journeys_over_limit = models.PositiveIntegerField(default=0, db_default=0)

    class Meta:
        indexes = [
            models.Index(fields=["team", "-deployed_at"], name="uj_deploy_team_deployed_idx"),
            # Serves the idempotency lookup for a retried announcement of the same commit.
            models.Index(fields=["team", "commit_sha", "-created_at"], name="uj_deploy_team_commit_idx"),
        ]
