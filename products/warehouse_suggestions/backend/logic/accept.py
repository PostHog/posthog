from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import asdict, fields
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from posthog.dataclasses import frozen

from products.data_catalog.backend.facade.api import certifications_for_team, certify, deprecate, propose_certification
from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.api import (
    IncrementalConfig,
    IncrementalConfigRefusedError,
    MaterializationFailedError,
    MaterializationForbiddenError,
    MaterializationRefusedError,
    SavedQueryNotFoundError,
    definition_database,
    enable_saved_query_materialization,
    get_saved_query_columns,
    get_saved_query_sql,
    get_saved_query_summary,
    propose_incremental_config,
)
from products.warehouse_sources.backend.facade.api import get_queryable_table

from ..facade.contracts import (
    AcceptFailedError,
    AcceptOptionRefusedError,
    AcceptOptions,
    CertificationAsset,
    CreatedAsset,
    MaterializationAsset,
    MaterializePayload,
    SubjectAlreadyCertifiedError,
    SubjectEditAccessRequiredError,
    SuggestionAlreadyDecidedError,
    SuggestionOutdatedError,
    SuggestionPayload,
    SuggestionSubjectGoneError,
)
from ..facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionRefreshMode,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)
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
    options: AcceptOptions
    was_impersonated: bool


class Acceptor(ABC):
    option_fields: ClassVar[frozenset[str]] = frozenset()

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


VIEW_CHANGED_SINCE_SUGGESTED = (
    "This view changed after the suggestion was made, so it can no longer refresh incrementally on the suggested keys."
)
OPTION_NOT_APPLICABLE = "This option does not apply to a {kind} suggestion."
KEYS_NEED_INCREMENTAL = (
    "incremental_key, unique_key and lookback_seconds only apply to an incremental refresh. "
    "Set refresh_mode to incremental to use them."
)
KEYS_REQUIRED = (
    "An incremental refresh needs an incremental_key and a unique_key. Choose them with view-check-incremental."
)
REFRESH_INTERVAL_FIELD = "refresh_interval_seconds"
REFRESH_MODE_FIELD = "refresh_mode"
INCREMENTAL_KEY_FIELD = "incremental_key"
UNIQUE_KEY_FIELD = "unique_key"


class MaterializeAcceptor(Acceptor):
    option_fields = frozenset(field.name for field in fields(AcceptOptions))

    def accept(
        self, suggestion: WarehouseSuggestion, payload: SuggestionPayload, request: AcceptRequest
    ) -> CreatedAsset:
        if not isinstance(payload, MaterializePayload):
            raise AcceptFailedError("This suggestion has no refresh interval to apply.")
        options = request.options
        interval = timedelta(seconds=options.refresh_interval_seconds or payload.refresh_interval_seconds)
        incremental_config = _incremental_config(payload, options)
        if (
            incremental_config is not None
            and not _chose_keys(options)
            and not _still_proposed(suggestion, incremental_config, request.user)
        ):
            raise SuggestionOutdatedError(VIEW_CHANGED_SINCE_SUGGESTED)
        try:
            enable_saved_query_materialization(
                suggestion.team_id,
                suggestion.subject_id,
                user=request.user,
                sync_frequency_interval=interval,
                visible_blocker_names=_no_blocker_names,
                was_impersonated=request.was_impersonated,
                incremental_config=incremental_config,
            )
        except SavedQueryNotFoundError:
            raise SuggestionSubjectGoneError(WarehouseSuggestionSubjectKind.SAVED_QUERY)
        except MaterializationForbiddenError:
            raise SubjectEditAccessRequiredError(WarehouseSuggestionSubjectKind.SAVED_QUERY)
        except IncrementalConfigRefusedError as error:
            raise _incremental_refusal(error, options)
        except MaterializationRefusedError as error:
            raise AcceptOptionRefusedError(REFRESH_INTERVAL_FIELD, str(error))
        except MaterializationFailedError as error:
            raise AcceptFailedError(str(error))
        return _materialization_asset(suggestion, interval, incremental_config)


def _incremental_config(payload: MaterializePayload, options: AcceptOptions) -> IncrementalConfig | None:
    if (options.refresh_mode or payload.refresh_mode) == WarehouseSuggestionRefreshMode.FULL:
        if _chose_keys(options) or options.lookback_seconds is not None:
            raise AcceptOptionRefusedError(REFRESH_MODE_FIELD, KEYS_NEED_INCREMENTAL)
        return None
    incremental_key = options.incremental_key or payload.incremental_key
    if incremental_key is None:
        raise AcceptOptionRefusedError(INCREMENTAL_KEY_FIELD, KEYS_REQUIRED)
    unique_key = options.unique_key or payload.unique_key
    if not unique_key:
        raise AcceptOptionRefusedError(UNIQUE_KEY_FIELD, KEYS_REQUIRED)
    return IncrementalConfig(
        incremental_key=incremental_key,
        unique_key=unique_key,
        lookback_seconds=payload.lookback_seconds if options.lookback_seconds is None else options.lookback_seconds,
    )


def _incremental_refusal(error: IncrementalConfigRefusedError, options: AcceptOptions) -> Exception:
    if not _chose_keys(options):
        return SuggestionOutdatedError(f"{VIEW_CHANGED_SINCE_SUGGESTED} {error}")
    refused_key = error.refused_keys[0] if error.refused_keys else INCREMENTAL_KEY_FIELD
    return AcceptOptionRefusedError(refused_key, str(error))


def _still_proposed(suggestion: WarehouseSuggestion, config: IncrementalConfig, user: "User") -> bool:
    proposed = propose_incremental_config(
        get_saved_query_sql(suggestion.team_id, suggestion.subject_id) or "",
        get_saved_query_columns(suggestion.team_id, suggestion.subject_id),
        database=definition_database(suggestion.team_id, user=user),
    )
    return (
        proposed is not None
        and proposed.incremental_key == config.incremental_key
        and set(proposed.unique_key) == set(config.unique_key)
    )


def _chose_keys(options: AcceptOptions) -> bool:
    return options.incremental_key is not None or options.unique_key is not None


def _materialization_asset(
    suggestion: WarehouseSuggestion, interval: timedelta, incremental_config: IncrementalConfig | None
) -> MaterializationAsset:
    return MaterializationAsset(
        saved_query_id=str(suggestion.subject_id),
        refresh_interval_seconds=int(interval.total_seconds()),
        refresh_mode=WarehouseSuggestionRefreshMode.INCREMENTAL
        if incremental_config
        else WarehouseSuggestionRefreshMode.FULL,
        incremental_key=incremental_config.incremental_key if incremental_config else None,
        unique_key=incremental_config.unique_key if incremental_config else (),
        lookback_seconds=incremental_config.lookback_seconds if incremental_config else 0,
    )


def chosen_fields(options: AcceptOptions) -> tuple[str, ...]:
    return tuple(field.name for field in fields(options) if getattr(options, field.name) is not None)


def changed_fields(options: AcceptOptions, payload: SuggestionPayload) -> tuple[str, ...]:
    return tuple(name for name in chosen_fields(options) if getattr(payload, name, None) != getattr(options, name))


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
    changed_fields: tuple[str, ...] = ()


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
    kind = WarehouseSuggestionKind(suggestion.kind)
    acceptor = ACCEPTORS[kind]
    _refuse_options_the_kind_ignores(acceptor, kind, request.options)
    status = WarehouseSuggestionStatus(suggestion.status)
    if status == WarehouseSuggestionStatus.ACCEPTED:
        return AcceptOutcome(suggestion=suggestion, newly_accepted=False)
    if status != WarehouseSuggestionStatus.PROPOSED:
        raise SuggestionAlreadyDecidedError(status, WarehouseSuggestionStatus.ACCEPTED)
    if not _subject_exists(suggestion):
        raise SuggestionSubjectGoneError(WarehouseSuggestionSubjectKind(suggestion.subject_kind))
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
        created_asset = acceptor.accept(claimed, payload, request)
    except Exception:
        transition_to(
            suggestion.id, team_id, WarehouseSuggestionStatus.PROPOSED, user_id=None, transitions=RELEASE_TRANSITIONS
        )
        raise
    claimed.created_asset = asdict(created_asset)
    claimed.save(update_fields=["created_asset"])
    return AcceptOutcome(
        suggestion=claimed, newly_accepted=True, changed_fields=changed_fields(request.options, payload)
    )


def _refuse_options_the_kind_ignores(acceptor: Acceptor, kind: WarehouseSuggestionKind, options: AcceptOptions) -> None:
    ignored = [name for name in chosen_fields(options) if name not in acceptor.option_fields]
    if ignored:
        raise AcceptOptionRefusedError(ignored[0], OPTION_NOT_APPLICABLE.format(kind=kind))


def _subject_exists(suggestion: WarehouseSuggestion) -> bool:
    if suggestion.subject_kind == WarehouseSuggestionSubjectKind.TABLE:
        return get_queryable_table(suggestion.subject_id, suggestion.team_id) is not None
    return get_saved_query_summary(suggestion.team_id, suggestion.subject_id) is not None


def _no_blocker_names(bounds: "SavedQueryFrequencyBounds") -> dict[str, str]:
    return {}
