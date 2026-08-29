"""Viewer-specific access checks for shared report metric snapshots.

Metric snapshots are materialized without a requesting user, while report reads are authorized as
the viewer. A snapshot (or its query definition) must therefore be hidden whenever the two access
contexts are not equivalent. The policy is deliberately conservative: when a property restriction
or an unfamiliar series shape prevents us from proving the definition safe, the metric remains in
the response but its data-bearing fields are redacted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import cached_property

from rest_framework.request import Request

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.models import Team, User
from posthog.permissions import get_authenticator_scopes

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.property_access_control import (
    get_restricted_properties_with_group_type_index_for_team,
)


class ReportMetricAccessPolicy:
    """Decide which data-bearing fields of a report metric this request may read."""

    def __init__(self, *, request: Request | None, team: Team | None) -> None:
        self._team = team
        request_user = getattr(request, "user", None)
        self._user = request_user if isinstance(request_user, User) else None
        authenticator = getattr(request, "successful_authenticator", None)
        self._token_scopes = get_authenticator_scopes(authenticator) if request is not None else []

    def may_read_query(self, metric: Mapping[str, object]) -> bool:
        """Whether the stored definition itself is safe to return to this viewer."""

        if self._user is None or self._team is None or not self._token_grants("query"):
            return False

        query = metric.get("query")
        if query is None:
            # Current authoring requires a query. Treat legacy or manually corrupted queryless rows
            # as untrusted: their resource and property provenance cannot be proven.
            return False

        # A definition can carry restricted property names and literal filter values. Existing
        # query execution strips or blocks their use, but serializing the JSON would bypass that
        # layer. Until we can prove relevance for every nested filter shape, fail closed whenever
        # this viewer has any property restriction.
        if self._viewer_property_restrictions:
            return False

        series = self._trends_series(query)
        if series is None:
            return False

        for item in series:
            kind = item.get("kind")
            if kind == "EventsNode":
                event = item.get("event")
                if not isinstance(event, str) or not event or not self._token_grants("event_definition"):
                    return False
            elif kind == "ActionsNode":
                action_id = item.get("id")
                if (
                    not isinstance(action_id, int)
                    or isinstance(action_id, bool)
                    or action_id <= 0
                    or not self._token_grants("action")
                    or not self._may_read_action(action_id)
                ):
                    return False
            else:
                # Current authoring rejects other Trends series. Keep this fail-closed branch for
                # legacy or manually corrupted rows so report reads never bypass resource gates.
                return False

        return True

    def may_read_snapshot(self, metric: Mapping[str, object]) -> bool:
        """Whether a userless materialized value is equivalent to this viewer's access."""

        if not self.may_read_query(metric):
            return False

        # The materializer runs with user=None, which applies default property rules. Even an
        # unrestricted viewer (for example, one with a member-specific grant) must not receive that
        # shared result when the materializer had a different property-access fingerprint.
        return not self._materializer_property_restrictions

    @cached_property
    def _viewer_property_restrictions(self) -> frozenset[RestrictedProperty]:
        if self._user is None or self._team is None:
            return frozenset()
        return frozenset(get_restricted_properties_with_group_type_index_for_team(user=self._user, team=self._team))

    @cached_property
    def _materializer_property_restrictions(self) -> frozenset[RestrictedProperty]:
        if self._team is None:
            return frozenset()
        return frozenset(get_restricted_properties_with_group_type_index_for_team(user=None, team=self._team))

    @cached_property
    def _user_access_control(self) -> UserAccessControl | None:
        if self._user is None or self._team is None:
            return None
        return UserAccessControl(user=self._user, team=self._team)

    def _token_grants(self, resource: str) -> bool:
        scopes = self._token_scopes
        if scopes is None:
            return True
        return "*" in scopes or f"{resource}:read" in scopes or f"{resource}:write" in scopes

    def _may_read_action(self, action_id: int) -> bool:
        access_control = self._user_access_control
        if access_control is None:
            return False

        action_key = str(action_id)
        if action_key in access_control.blocked_resource_ids_by_scope.get("action", frozenset()):
            return False
        if access_control.has_resource_access("action"):
            return True
        # Object grants remain readable when the action resource as a whole is denied. Creator
        # access cannot be proven without loading each action, so the snapshot stays hidden in that
        # case rather than introducing an unbounded query-per-metric list path.
        return action_key in access_control.allowlisted_resource_ids_by_scope.get("action", frozenset())

    @staticmethod
    def _trends_series(query: object) -> Sequence[Mapping[str, object]] | None:
        if not isinstance(query, Mapping) or query.get("kind") != "InsightVizNode":
            return None
        source = query.get("source")
        if not isinstance(source, Mapping) or source.get("kind") != "TrendsQuery":
            return None
        series = source.get("series")
        if not isinstance(series, list) or not series or any(not isinstance(item, Mapping) for item in series):
            return None
        return series
