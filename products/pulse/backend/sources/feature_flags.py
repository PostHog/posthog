from datetime import timedelta

from django.utils import timezone

from posthog.models.team import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import EvidenceRef, SourceItem, build_fingerprint_hint

MAX_FLAGS = 15


class FeatureFlagRolloutSource:
    """Feature flags launched in the window. A rollout is context that may explain metric
    movements, and a seed the agent can investigate further via its feature_flag:read MCP tools."""

    name = "feature_flags"

    def gather(self, team: Team, config: BriefConfig | None, period_days: int) -> list[SourceItem]:
        now = timezone.now()
        flags = FeatureFlag.objects.filter(
            team=team,
            deleted=False,
            active=True,
            created_at__gte=now - timedelta(days=period_days),
        ).order_by("-created_at")[:MAX_FLAGS]
        items: list[SourceItem] = []
        for flag in flags:
            metadata = flag.get_analytics_metadata()
            variant_note = f", {metadata['variants_count']} variants" if metadata["has_variants"] else ""
            # flag.key is user-authored free text; sanitized once at the prompt-render boundary.
            items.append(
                SourceItem(
                    source=self.name,
                    kind="context",
                    title=f"Feature flag '{flag.key}' launched",
                    description=(
                        f"The feature flag '{flag.key}' was created {flag.created_at:%Y-%m-%d} "
                        f"with {metadata['groups_count']} release condition(s){variant_note}. "
                        "A newly launched flag can explain movements in the metrics it gates."
                    ),
                    numbers={
                        "release_conditions": metadata["groups_count"],
                        "variants": metadata["variants_count"],
                    },
                    evidence=[EvidenceRef(type="flag", ref=str(flag.pk), label=flag.key)],
                    fingerprint_hint=build_fingerprint_hint(self.name, str(flag.pk)),
                )
            )
        return items
