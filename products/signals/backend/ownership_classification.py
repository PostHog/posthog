from __future__ import annotations

from django.db import transaction

from rest_framework import serializers

from products.signals.backend.models import SignalProductDomain, SignalReport, SignalRoutingProposal


def record_routing_proposal(*, team_id: int, report_id, data: dict) -> SignalRoutingProposal:
    """Shadow output is deliberately separate from the accepted routing and reviewer store."""
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
        if report.updated_at != data["report_revision"]:
            raise serializers.ValidationError("The report changed. Classify its current revision.")
        domain = None
        if data["domain_id"] is not None:
            domain = (
                SignalProductDomain.objects.for_team(team_id)
                .select_for_update()
                .filter(id=data["domain_id"], archived=False)
                .first()
            )
            if domain is None or domain.revision != data.get("domain_revision"):
                raise serializers.ValidationError("The domain changed or is unavailable. Load the current definitions.")
        defaults = {key: value for key, value in data.items() if key not in ("domain_id", "method")}
        defaults.update(domain=domain, domain_revision=domain.revision if domain else None)
        proposal, _ = SignalRoutingProposal.objects.for_team(team_id).update_or_create(
            team_id=team_id, report=report, method=data["method"], defaults=defaults
        )
        return proposal
