from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING
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
    CertificationAsset,
    CreatedAsset,
    MaterializationAsset,
    MaterializePayload,
    RefreshIntervalRefusedError,
    SubjectAlreadyCertifiedError,
    SubjectEditAccessRequiredError,
    SuggestionAlreadyDecidedError,
    SuggestionPayload,
    SuggestionSubjectGoneError,
)
from ..facade.enums import WarehouseSuggestionKind, WarehouseSuggestionStatus, WarehouseSuggestionSubjectKind
from ..models import WarehouseSuggestion
from .analytics import SuggestionOutcome, report_outcomes
from .payloads import payload_from_json
from .suggestions import HUMAN_TRANSITIONS, Transitions, transition_to

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
    @abstractmethod
    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> CreatedAsset: ...


@frozen
class CertificationAcceptor(Acceptor):
    status: CertificationStatus
    apply: "Callable[[TableCertification, User], TableCertification]"
    reuses_existing: bool

    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> CreatedAsset:
        certification = self._certification(suggestion, request)
        self.apply(certification, request.user)
        return CertificationAsset(certification_id=str(certification.id))

    def _certification(self, suggestion: WarehouseSuggestion, request: AcceptRequest) -> "TableCertification":
        subject_kind = WarehouseSuggestionSubjectKind(suggestion.subject_kind)
        is_table = subject_kind == WarehouseSuggestionSubjectKind.TABLE
        table_id = suggestion.subject_id if is_table else None
        saved_query_id = None if is_table else suggestion.subject_id
        existing = (
            certifications_for_team(request.team).filter(table_id=table_id, saved_query_id=saved_query_id).first()
        )
        if existing is None:
            return propose_certification(
                team=request.team,
                user=request.user,
                table_id=table_id,
                saved_query_id=saved_query_id,
                proposed_status=self.status,
            )
        if not self.reuses_existing:
            raise SubjectAlreadyCertifiedError(subject_kind)
        return existing


class MaterializeAcceptor(Acceptor):
    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> CreatedAsset:
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
        return MaterializationAsset(
            saved_query_id=str(suggestion.subject_id), refresh_interval_seconds=int(interval.total_seconds())
        )


ACCEPTORS: Mapping[WarehouseSuggestionKind, Acceptor] = {
    WarehouseSuggestionKind.CERTIFY: CertificationAcceptor(
        status=CertificationStatus.CERTIFIED, apply=certify, reuses_existing=False
    ),
    WarehouseSuggestionKind.DEPRECATE: CertificationAcceptor(
        status=CertificationStatus.DEPRECATED, apply=deprecate, reuses_existing=True
    ),
    WarehouseSuggestionKind.MATERIALIZE: MaterializeAcceptor(),
}


RELEASE_TRANSITIONS: Transitions = {WarehouseSuggestionStatus.ACCEPTED: frozenset({WarehouseSuggestionStatus.PROPOSED})}


@frozen
class AcceptOutcome:
    suggestion: WarehouseSuggestion
    newly_accepted: bool


def accept(team_id: int, suggestion_id: UUID, request: AcceptRequest) -> AcceptOutcome:
    try:
        return _accept(team_id, suggestion_id, request)
    except (SuggestionSubjectGoneError, SubjectAlreadyCertifiedError):
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
    try:
        claimed = transition_to(
            suggestion.id,
            team_id,
            WarehouseSuggestionStatus.ACCEPTED,
            user_id=request.user.id,
            transitions=HUMAN_TRANSITIONS,
        )
    except SuggestionAlreadyDecidedError:
        current = WarehouseSuggestion.objects.for_team(team_id).get(id=suggestion_id)
        if current.status != WarehouseSuggestionStatus.ACCEPTED:
            raise
        return AcceptOutcome(suggestion=current, newly_accepted=False)
    try:
        created_asset = ACCEPTORS[kind].accept(claimed, payload, request)
    except Exception:
        transition_to(
            suggestion.id, team_id, WarehouseSuggestionStatus.PROPOSED, user_id=None, transitions=RELEASE_TRANSITIONS
        )
        raise
    claimed.created_asset = asdict(created_asset)
    claimed.save(update_fields=["created_asset"])
    return AcceptOutcome(suggestion=claimed, newly_accepted=True)


def _subject_exists(suggestion: WarehouseSuggestion) -> bool:
    if suggestion.subject_kind == WarehouseSuggestionSubjectKind.TABLE:
        return get_queryable_table(suggestion.subject_id, suggestion.team_id) is not None
    return get_saved_query_summary(suggestion.team_id, suggestion.subject_id) is not None


def _no_blocker_names(bounds: "SavedQueryFrequencyBounds") -> dict[str, str]:
    return {}
