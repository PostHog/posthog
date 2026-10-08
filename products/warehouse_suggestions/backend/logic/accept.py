from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_catalog.backend.facade.api import certifications_for_team, certify, deprecate, propose_certification
from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.api import (
    MaterializationFailedError,
    MaterializationForbiddenError,
    MaterializationRefusedError,
    SavedQueryNotFoundError,
    enable_saved_query_materialization,
    get_saved_query_summary,
)
from products.warehouse_sources.backend.facade.api import get_queryable_table

from ..facade.contracts import (
    AcceptFailedError,
    MaterializePayload,
    RefreshIntervalRefusedError,
    SubjectEditAccessRequiredError,
    SuggestionAlreadyDecidedError,
    SuggestionPayload,
    SuggestionSubjectGoneError,
)
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from ..models import WarehouseSuggestion
from .analytics import SuggestionOutcome, report_outcomes
from .payloads import payload_from_json
from .suggestions import HUMAN_TRANSITIONS, transition_to

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.data_catalog.backend.facade.api import TableCertification
    from products.data_modeling.backend.facade.api import SavedQueryFrequencyBounds


@frozen
class AcceptRequest:
    team: "Team"
    user: "User"
    refresh_interval: timedelta | None
    was_impersonated: bool


class Acceptor(ABC):
    kind: ClassVar[WarehouseSuggestionKind]

    @abstractmethod
    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> dict[str, Any]: ...


class CertifyAcceptor(Acceptor):
    kind = WarehouseSuggestionKind.CERTIFY

    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> dict[str, Any]:
        certification = _certification(suggestion, request, CertificationStatus.CERTIFIED)
        certify(certification, request.user)
        return {"certification_id": str(certification.id)}


class DeprecateAcceptor(Acceptor):
    kind = WarehouseSuggestionKind.DEPRECATE

    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> dict[str, Any]:
        certification = _certification(suggestion, request, CertificationStatus.DEPRECATED)
        deprecate(certification, request.user)
        return {"certification_id": str(certification.id)}


class MaterializeAcceptor(Acceptor):
    kind = WarehouseSuggestionKind.MATERIALIZE

    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> dict[str, Any]:
        if not isinstance(payload, MaterializePayload):
            raise AcceptFailedError("This suggestion has no refresh interval to apply.")
        interval = request.refresh_interval or timedelta(seconds=payload.refresh_interval_seconds)
        try:
            enable_saved_query_materialization(
                suggestion.team_id,
                suggestion.subject_id,
                user=request.user,
                sync_frequency_interval=interval,
                visible_blocker_names=_no_blocker_names,
                was_impersonated=request.was_impersonated,
            )
        except SavedQueryNotFoundError:
            raise SuggestionSubjectGoneError(WarehouseSuggestionSubjectKind.SAVED_QUERY)
        except MaterializationForbiddenError:
            raise SubjectEditAccessRequiredError(WarehouseSuggestionSubjectKind.SAVED_QUERY)
        except MaterializationRefusedError as error:
            raise RefreshIntervalRefusedError(str(error))
        except MaterializationFailedError as error:
            raise AcceptFailedError(str(error))
        return {"saved_query_id": str(suggestion.subject_id), "refresh_interval_seconds": int(interval.total_seconds())}


ACCEPTORS: Mapping[WarehouseSuggestionKind, Acceptor] = {
    WarehouseSuggestionKind.CERTIFY: CertifyAcceptor(),
    WarehouseSuggestionKind.DEPRECATE: DeprecateAcceptor(),
    WarehouseSuggestionKind.MATERIALIZE: MaterializeAcceptor(),
}


@frozen
class AcceptOutcome:
    suggestion: WarehouseSuggestion
    newly_accepted: bool


def accept(team_id: int, suggestion_id: UUID, request: AcceptRequest) -> AcceptOutcome:
    try:
        return _accept(team_id, suggestion_id, request)
    except SuggestionSubjectGoneError:
        resolved = _resolve_quietly(team_id, suggestion_id)
        if resolved is not None:
            report_outcomes(SuggestionOutcome.AUTO_RESOLVED, [resolved], team=request.team)
        raise


def _resolve_quietly(team_id: int, suggestion_id: UUID) -> WarehouseSuggestion | None:
    try:
        return transition_to(suggestion_id, team_id, WarehouseSuggestionStatus.AUTO_RESOLVED, user_id=None)
    except (SuggestionAlreadyDecidedError, WarehouseSuggestion.DoesNotExist):
        return None


def _accept(team_id: int, suggestion_id: UUID, request: AcceptRequest) -> AcceptOutcome:
    suggestion = WarehouseSuggestion.objects.for_team(team_id).get(id=suggestion_id)
    status = WarehouseSuggestionStatus(suggestion.status)
    if status == WarehouseSuggestionStatus.ACCEPTED:
        return AcceptOutcome(suggestion=suggestion, newly_accepted=False)
    if status != WarehouseSuggestionStatus.PROPOSED:
        raise SuggestionAlreadyDecidedError(status, WarehouseSuggestionStatus.ACCEPTED)
    if not _subject_exists(suggestion):
        raise SuggestionSubjectGoneError(WarehouseSuggestionSubjectKind(suggestion.subject_kind))
    kind = WarehouseSuggestionKind(suggestion.kind)
    payload = payload_from_json(kind, suggestion.payload_version, suggestion.payload)
    created_asset = ACCEPTORS[kind].accept(suggestion, payload, request)
    try:
        accepted = transition_to(
            suggestion.id,
            team_id,
            WarehouseSuggestionStatus.ACCEPTED,
            user_id=request.user.id,
            created_asset=created_asset,
            transitions=HUMAN_TRANSITIONS,
        )
    except SuggestionAlreadyDecidedError:
        current = WarehouseSuggestion.objects.for_team(team_id).get(id=suggestion_id)
        if current.status != WarehouseSuggestionStatus.ACCEPTED:
            raise
        return AcceptOutcome(suggestion=current, newly_accepted=False)
    return AcceptOutcome(suggestion=accepted, newly_accepted=True)


def _subject_exists(suggestion: WarehouseSuggestion) -> bool:
    if suggestion.subject_kind == WarehouseSuggestionSubjectKind.TABLE:
        return get_queryable_table(suggestion.subject_id, suggestion.team_id) is not None
    return get_saved_query_summary(suggestion.team_id, suggestion.subject_id) is not None


def _certification(
    suggestion: WarehouseSuggestion, request: AcceptRequest, status: CertificationStatus
) -> "TableCertification":
    certifications = certifications_for_team(request.team)
    if suggestion.subject_kind == WarehouseSuggestionSubjectKind.TABLE:
        existing = certifications.filter(table_id=suggestion.subject_id).first()
        return existing or propose_certification(
            team=request.team, user=request.user, table_id=suggestion.subject_id, proposed_status=status
        )
    existing = certifications.filter(saved_query_id=suggestion.subject_id).first()
    return existing or propose_certification(
        team=request.team, user=request.user, saved_query_id=suggestion.subject_id, proposed_status=status
    )


def _no_blocker_names(bounds: "SavedQueryFrequencyBounds") -> dict[str, str]:
    return {}
