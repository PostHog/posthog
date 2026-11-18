import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import OuterRef, Subquery

from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.enrichment.icp_lists import build_curated_lists
from products.growth.backend.enrichment.scoring_lab import preview_company
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichmentFetch


def _result_summary(result: IcpFitResult) -> dict[str, Any]:
    return {
        "score": result.score,
        "status": result.status,
        "components": result.components,
        "dq_reason": result.dq_reason,
        "flags": result.flags,
    }


class Command(BaseCommand):
    help = "Compare a saved scoring version with the active version using archived enrichment. No providers or writes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--config-version", required=True)
        parser.add_argument("--limit", type=int, default=100, help="Recent organizations to compare (1 to 1000)")

    def handle(self, *args: Any, **options: Any) -> None:
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
        candidate = IcpScoringConfig.objects.filter(version=options["config_version"]).first()
        if candidate is None:
            raise CommandError("The candidate scoring version does not exist")
        active = IcpScoringConfig.objects.filter(is_active=True).first()
        if active is None:
            raise CommandError("No active scoring version exists to compare")
        candidate_lists, active_lists = build_curated_lists(candidate), build_curated_lists(active)
        latest = (
            OrganizationEnrichmentFetch.objects.filter(organization_id=OuterRef("organization_id"))
            .order_by("-fetched_at", "-id")
            .values("id")[:1]
        )
        fetches = (
            OrganizationEnrichmentFetch.objects.filter(pk=Subquery(latest))
            .select_related("organization")
            .order_by("-fetched_at", "-id")[:limit]
        )
        samples = []
        for fetch in fetches:
            preview = preview_company(fetch, active_lists, candidate_lists)
            if preview.error is not None or preview.active is None or preview.preview is None:
                raise CommandError(f"Could not preview organization {fetch.organization_id}: {preview.error}")
            before, after = preview.active, preview.preview
            before_components, after_components = before.components or {}, after.components or {}
            samples.append(
                {
                    "organization_id": str(fetch.organization_id),
                    "fetch_id": str(fetch.id),
                    "active": _result_summary(before),
                    "candidate": _result_summary(after),
                    "score_delta": after.score - before.score
                    if after.score is not None and before.score is not None
                    else None,
                    "component_deltas": {
                        key: after_components.get(key, 0) - before_components.get(key, 0)
                        for key in sorted(before_components.keys() | after_components.keys())
                    },
                }
            )
        self.stdout.write(
            json.dumps(
                {
                    "active_version": active.version,
                    "candidate_version": candidate.version,
                    "sample_count": len(samples),
                    "changed": sum(sample["active"] != sample["candidate"] for sample in samples),
                    "samples": samples,
                },
                indent=2,
            )
        )
