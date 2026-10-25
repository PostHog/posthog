import hashlib
from typing import TYPE_CHECKING

from django.utils import timezone

from products.data_modeling.backend.facade.api import prepare_saved_query_repair

from ..facade.contracts import PAYLOAD_VERSION, ProposeSqlRepair, SqlRepairPayload, SqlRepairValidation, SuggestionDraft
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from ..models import WarehouseSuggestion
from .analytics import SuggestionOutcome, report_outcomes
from .rules import RULES, rules_version
from .suggestions import upsert_suggestions

if TYPE_CHECKING:
    from posthog.models import Team, User


def propose_sql_repair(team: "Team", proposal: ProposeSqlRepair, *, user: "User") -> WarehouseSuggestion:
    plan = prepare_saved_query_repair(team.pk, proposal.saved_query_id, proposal.proposed_query, user=user)
    now = timezone.now()
    draft = SuggestionDraft(
        kind=WarehouseSuggestionKind.SQL_REPAIR,
        fingerprint=_fingerprint(str(plan.saved_query_id), plan.original_query_hash, plan.proposed_query),
        subject_kind=WarehouseSuggestionSubjectKind.SAVED_QUERY,
        subject_id=plan.saved_query_id,
        payload=SqlRepairPayload(
            subject_name=plan.subject_name,
            original_query=plan.original_query,
            original_query_revision=plan.original_query_revision,
            original_query_hash=plan.original_query_hash,
            proposed_query=plan.proposed_query,
            failure_evidence=proposal.failure_evidence,
            reason=proposal.reason,
            expected_effect=proposal.expected_effect,
            validation=SqlRepairValidation(
                syntax_valid=plan.validation.syntax_valid,
                references_valid=plan.validation.references_valid,
                result_schema_compatible=plan.validation.result_schema_compatible,
                read_only=plan.validation.read_only,
                rows_returned=plan.validation.rows_returned,
                max_execution_seconds=plan.validation.max_execution_seconds,
                business_equivalence_checked=plan.validation.business_equivalence_checked,
            ),
        ),
        payload_version=PAYLOAD_VERSION,
        rules_version=rules_version(RULES),
        evidence={},
        evidence_window_start=now,
        evidence_window_end=now,
        score=1.0,
        score_inputs={},
        run_id="",
    )
    existing = WarehouseSuggestion.objects.for_team(team.pk).filter(fingerprint=draft.fingerprint).first()
    upsert_suggestions(team.pk, [draft])
    suggestion = WarehouseSuggestion.objects.for_team(team.pk).get(fingerprint=draft.fingerprint)
    surfaced = suggestion.surfaced_at is None and suggestion.status == WarehouseSuggestionStatus.PROPOSED
    if surfaced:
        WarehouseSuggestion.objects.for_team(team.pk).filter(id=suggestion.id, surfaced_at__isnull=True).update(
            surfaced_at=now
        )
        suggestion.surfaced_at = now
    if existing is None:
        report_outcomes(SuggestionOutcome.CREATED, [suggestion], team=team, user=user)
    if surfaced:
        report_outcomes(SuggestionOutcome.SURFACED, [suggestion], team=team, user=user)
    return suggestion


def _fingerprint(saved_query_id: str, original_query_hash: str, proposed_query: str) -> str:
    proposed_hash = hashlib.sha256(proposed_query.encode()).hexdigest()
    return hashlib.sha256(f"{saved_query_id}:{original_query_hash}:{proposed_hash}".encode()).hexdigest()
