from datetime import timedelta

from django.utils import timezone

from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.annotations.backend.facade import api as annotations_api
from products.pulse.backend.config import BriefSettings
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind

TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 500


class AnnotationsSource:
    """Team + org-scoped annotations in the period, surfaced as context items — humans marking
    "something happened here" (deploys, releases) become causal candidates for the narrative."""

    name = "annotations"

    def gather(
        self, team: Team, config: BriefConfig | None, lookback_days: int, user_access_control: UserAccessControl
    ) -> list[SourceItem]:
        now = timezone.now()
        # Scope is deliberately unrestricted, unlike the AI context of one insight or dashboard: a brief
        # has no single target, so every annotation the team can see is a valid causal marker.
        annotations = annotations_api.list_dated_annotations(
            team_id=team.id,
            organization_id=team.organization_id,
            start=now - timedelta(days=lookback_days),
            end=now,
            limit=BriefSettings.from_config(config).max_annotations,
        )
        items: list[SourceItem] = []
        for annotation in annotations:
            # Untrusted free text is sanitized once at the prompt-render boundary (_render_items).
            content = annotation.content
            items.append(
                SourceItem(
                    source=self.name,
                    kind=SourceItemKind.CONTEXT,
                    title=content[:TITLE_MAX_CHARS],
                    description=(
                        f"{content[:DESCRIPTION_MAX_CHARS]} — annotation marked "
                        f"{annotation.marked_at:%Y-%m-%d} ({annotation.scope.label} scope)."
                    ),
                    # Annotations have no standalone view; the ResourceLink FK carries the linkage.
                    evidence=[
                        EvidenceRef(
                            type=EvidenceType.ANNOTATION,
                            ref=str(annotation.id),
                            label=content[:TITLE_MAX_CHARS],
                            url="",
                        )
                    ],
                    fingerprint_hint=f"annotation:{annotation.id}",
                )
            )
        return items
