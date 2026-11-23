"""Entities that exist in a project and that no stack manages, shaped as description bodies for `pull --adopt`.

The engine reads them through the kind's own API with a token minted for the caller, so that API's own
visibility rules decide what the caller sees.
"""

from __future__ import annotations

from .. import engine_adapter
from ..engine_adapter import EngineFailure
from ..facade.contracts import AdoptableEntity, AdoptablePage, Caller, StackServiceError
from ..facade.enums import StackErrorKind
from . import credentials, grants, kinds
from .credentials import CallerUnavailable
from .stacks import managed_entity_ids

MAX_LIMIT = 100


def _caller_credentials(caller: Caller, kind: str, *, write: bool):  # noqa: ANN202 — (token, credentials)
    authority = grants.check_grant(
        user_id=caller.user_id, target_team_id=caller.target_team_id, grant=grants.grant_dict(caller.grant)
    )
    return credentials.mint(
        user=authority.user,
        target_team_id=caller.target_team_id,
        scopes=authority.narrow(kinds.run_scopes([kind], write=write)),
        expires_at=authority.expires_at,
    )


def _failed(failure: EngineFailure) -> StackServiceError:
    first = failure.errors[0] if failure.errors else {}
    if first.get("code") == "runner_unavailable":
        return StackServiceError(StackErrorKind.UNAVAILABLE, "runner_unavailable", str(first.get("message", "")))
    return StackServiceError(
        StackErrorKind.INVALID, str(first.get("code", "read_failed")), str(first.get("message", ""))
    )


def list_adoptable(team_id: int, caller: Caller, kind: str, *, cursor: str | None, limit: int) -> AdoptablePage:
    kinds.kind_scopes(kind)
    if engine_adapter.ownership_scope(kind) == "organization":
        # Listing every entity of an organization-wide kind needs an organization route, which refuses the
        # project-scoped token a run mints. Adopt such an entity by its id instead.
        raise StackServiceError(
            StackErrorKind.INVALID,
            "kind_not_listable",
            f"Listing {kind} entities to adopt is not available. Adopt one by its id with the adopt call.",
        )
    try:
        token, engine_credentials = _caller_credentials(caller, kind, write=False)
    except CallerUnavailable as error:
        raise StackServiceError(StackErrorKind.FORBIDDEN, "caller_unavailable", str(error)) from error
    try:
        page = engine_adapter.read_entities(kind, engine_credentials, cursor=cursor, limit=min(limit, MAX_LIMIT))
    except EngineFailure as failure:
        raise _failed(failure) from failure
    finally:
        credentials.revoke(token.id)
    managed = managed_entity_ids(team_id, kind)
    return AdoptablePage(
        results=[
            AdoptableEntity(kind=kind, entity_id=item.entity_id, name=item.name, body=item.body)
            for item in page.results
            if item.entity_id not in managed
        ],
        next_cursor=page.next_cursor,
    )


def canonical_ids(caller: Caller, resources: list[tuple[str, str, str]]) -> dict[tuple[str, str], str]:
    """The id each entity's own API returns, read with the caller's write scopes for its kind.

    Refuses an entity the caller cannot see, or that does not exist.
    """
    found: dict[tuple[str, str], str] = {}
    for kind in sorted({kind for kind, _, _ in resources}):
        wanted = [(key, entity_id) for resource_kind, key, entity_id in resources if resource_kind == kind]
        try:
            token, engine_credentials = _caller_credentials(caller, kind, write=True)
        except CallerUnavailable as error:
            raise StackServiceError(StackErrorKind.FORBIDDEN, "caller_unavailable", str(error)) from error
        try:
            page = engine_adapter.read_entities(
                kind, engine_credentials, ids=[entity_id for _, entity_id in wanted], limit=len(wanted)
            )
        except EngineFailure as failure:
            raise _failed(failure) from failure
        finally:
            credentials.revoke(token.id)
        returned = {item.entity_id for item in page.results}
        for key, entity_id in wanted:
            canonical = entity_id if entity_id in returned else _match(entity_id, returned)
            if canonical is None:
                raise StackServiceError(
                    StackErrorKind.NOT_FOUND,
                    "entity_not_found",
                    f"No {kind} with the id {entity_id} exists in this project that you can edit.",
                )
            found[(kind, key)] = canonical
    return found


def _match(entity_id: str, returned: set[str]) -> str | None:
    """The returned id that spells the same entity, such as `042` for `42`."""
    stripped = entity_id.lstrip("0") or "0"
    return next((candidate for candidate in returned if candidate.lstrip("0") == stripped), None)
