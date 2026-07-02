from datetime import timedelta

from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.models.team import Team

from products.annotations.backend.models import Annotation
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem

MAX_ANNOTATIONS = 20
TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 500


class AnnotationsSource:
    name = "annotations"

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]:
        now = timezone.now()
        annotations = (
            Annotation.objects.filter(
                Q(team=team) | Q(scope=Annotation.Scope.ORGANIZATION, organization_id=team.organization_id),
                deleted=False,
                content__isnull=False,
            )
            .exclude(content="")
            .annotate(effective_date=Coalesce(F("date_marker"), F("created_at")))
            .filter(effective_date__gte=now - timedelta(days=period_days), effective_date__lte=now)
            .order_by("-effective_date")[:MAX_ANNOTATIONS]
        )
        items: list[SourceItem] = []
        for annotation in annotations:
            content = annotation.content or ""
            effective_date = annotation.date_marker or annotation.created_at or now
            items.append(
                SourceItem(
                    source=self.name,
                    kind="context",
                    title=content[:TITLE_MAX_CHARS],
                    description=(
                        f"{content[:DESCRIPTION_MAX_CHARS]} — annotation marked "
                        f"{effective_date:%Y-%m-%d} ({annotation.get_scope_display()} scope)."
                    ),
                    numbers={},
                    evidence=[EvidenceRef(type="annotation", ref=str(annotation.id), label=content[:TITLE_MAX_CHARS])],
                    fingerprint_hint=f"annotation:{annotation.id}",
                )
            )
        return items
