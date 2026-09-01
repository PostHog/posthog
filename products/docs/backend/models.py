"""
Django models for docs.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

import uuid

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin

from .facade.enums import SplineStatus


# Inherits TeamScopedRootMixin so models opt into fail-closed team scoping —
# queries without team context raise TeamScopeError instead of silently
# returning every team's rows. See posthog/models/scoping/README.md.
# Main-DB products (TeamScopedRootMixin): add `team = models.ForeignKey(
# "posthog.Team", on_delete=models.CASCADE)` to the subclass.
class SplineReticulator(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in SplineStatus],
        default=SplineStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name
