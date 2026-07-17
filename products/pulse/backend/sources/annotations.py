from datetime import timedelta

from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.models.team import Team

from products.annotations.backend.models import Annotation
from products.pulse.backend.config import MAX_ANNOTATIONS
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, EvidenceType, SourceItem, SourceItemKind

TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 500


class AnnotationsSource:
    """Team + org-scoped annotations in the period, surfaced as context items — humans marking
    "something happened here" (deploys, releases) become causal candidates for the narrative."""

    name = "annotations"

    def gather(self, team: Team, config: BriefConfig | None, lookback_days: int) -> list[SourceItem]:
        now = timezone.now()
        # Visibility matches the annotations AI-context path (team + same-org). Scope is deliberately
        # unrestricted, unlike get_annotations_for_ai_context (which defaults to PROJECT/ORGANIZATION):
        # a brief has no single insight/dashboard target, so every team-owned annotation is a valid
        # causal marker for the narrative. All entries are team- or same-org-scoped — no cross-team leak.
        annotations = (
            Annotation.objects.filter(
                Q(team=team) | Q(scope=Annotation.Scope.ORGANIZATION, organization_id=team.organization_id),
                deleted=False,
                content__isnull=False,
            )
            .exclude(content="")
            .annotate(effective_date=Coalesce(F("date_marker"), F("created_at")))
            .filter(effective_date__gte=now - timedelta(days=lookback_days), effective_date__lte=now)
            .order_by("-effective_date")[:MAX_ANNOTATIONS]
        )
        items: list[SourceItem] = []
        for annotation in annotations:
            # Untrusted free text is sanitized once at the prompt-render boundary (_render_items).
            # The queryset excludes null/empty content, but guard at runtime too (a concurrent update
            # could null it between query and iteration; `assert` would be stripped under `python -O`).
            content = annotation.content
            if content is None:
                continue
            items.append(
                SourceItem(
                    source=self.name,
                    kind=SourceItemKind.CONTEXT,
                    title=content[:TITLE_MAX_CHARS],
                    description=(
                        f"{content[:DESCRIPTION_MAX_CHARS]} — annotation marked "
                        f"{annotation.effective_date:%Y-%m-%d} ({annotation.get_scope_display()} scope)."
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
