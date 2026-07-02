from datetime import timedelta

from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.models.team import Team

from products.annotations.backend.models import Annotation
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem, build_fingerprint_hint

MAX_ANNOTATIONS = 20
TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 500

# Annotation content is user-authored free text headed into the synthesize prompt. Mirrors
# format_annotations_for_prompt (products/annotations/backend/api/annotation_context.py):
# strip every Unicode line terminator so hand-crafted content can't fake a new input item,
# and neutralize angle brackets so it can't forge tag-scoped prompt structure.
_LINE_BREAK_CHARS = "\n\r\u2028\u2029\u0085\v\f"
_PROMPT_SAFE_TRANSLATION = str.maketrans({**dict.fromkeys(_LINE_BREAK_CHARS, " "), "<": "‹", ">": "›"})


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
            content = annotation.content.translate(_PROMPT_SAFE_TRANSLATION)
            items.append(
                SourceItem(
                    source=self.name,
                    kind="context",
                    title=content[:TITLE_MAX_CHARS],
                    description=(
                        f"{content[:DESCRIPTION_MAX_CHARS]} — annotation marked "
                        f"{annotation.effective_date:%Y-%m-%d} ({annotation.get_scope_display()} scope)."
                    ),
                    numbers={},
                    evidence=[EvidenceRef(type="annotation", ref=str(annotation.id), label=content[:TITLE_MAX_CHARS])],
                    fingerprint_hint=build_fingerprint_hint(self.name, str(annotation.id)),
                )
            )
        return items
