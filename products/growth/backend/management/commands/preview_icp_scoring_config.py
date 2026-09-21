import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import OuterRef, Subquery

from products.growth.backend.enrichment import gates
from products.growth.backend.enrichment.fit_recomputation import score_archived_fit
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.enrichment.icp_lists import build_curated_lists
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch


def _result_summary(result: IcpFitResult) -> dict[str, Any]:
    return {
        "score": result.score,
        "status": result.status,
        "components": result.components,
        "dq_reason": result.dq_reason,
        "data_coverage": result.data_coverage,
        "low_confidence": result.low_confidence,
        "quality_investor": result.quality_investor,
        "ai_pilled_source": result.ai_pilled_source,
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
        fetches = OrganizationEnrichmentFetch.objects.filter(pk=Subquery(latest)).order_by("-fetched_at", "-id")[:limit]
        samples = []
        for fetch in fetches:
            with transaction.atomic():
                record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
                data = record.data if record and isinstance(record.data, dict) else {}
                identity = gates.resolve_signup_identity(str(fetch.organization_id))
                domain = identity.domain if isinstance(identity, gates.SignupIdentity) else None
                flags = data.get("icp_fit_flags")
                wizard = isinstance(flags, dict) and flags.get("wizard_ai_sdk") is True
                results = [
                    score_archived_fit(
                        fetch,
                        lists=lists,
                        domain=domain,
                        role=data.get("signup_role"),
                        wizard_ai_sdk=wizard,
                    )
                    for lists in (active_lists, candidate_lists)
                ]
            before, after = results
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
