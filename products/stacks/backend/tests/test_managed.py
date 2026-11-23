from __future__ import annotations

import inspect
from datetime import timedelta
from typing import Any
from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.apps import apps
from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.managed_writes import guarded_model_labels

from products.feature_flags.backend.models import FeatureFlag
from products.stacks.backend.logic import credentials, managed
from products.stacks.backend.models import Stack, StackBinding, StackDiff
from products.stacks.backend.tests.base import StackAPITestBase

# Kinds whose model no routed viewset loads through a queryset, so the write lock cannot see their writes yet.
UNGUARDED_KINDS: frozenset[str] = frozenset()


class TestManagedInCode(StackAPITestBase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.flag = FeatureFlag.objects.create(team=self.team, key="beta", name="Beta", created_by=self.user)
        self.stack = Stack.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            target_team_id=self.team.id,
            name="web",
            repository="org/web",
            organization_id=str(self.organization.id),
        )
        self.binding = StackBinding.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            stack=self.stack,
            kind="flag",
            key="beta",
            entity_id=str(self.flag.id),
            source_file=".ph/flags.ts",
            source_export="beta",
            claim_scope=f"team:{self.team.id}",
            owned_fields=["ensure_experience_continuity", "key", "name", "tags"],
        )
        managed.restore_markers()

    def flag_url(self) -> str:
        return f"/api/projects/{self.team.id}/feature_flags/{self.flag.id}/"

    def patch_flag(self, body: dict[str, Any], **extra: Any):
        return self.client.patch(self.flag_url(), body, format="json", **extra)

    def test_a_write_to_an_owned_field_is_refused_and_names_the_file(self) -> None:
        response = self.patch_flag({"name": "Renamed in the UI"})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        body = response.json()
        assert body["code"] == "managed_in_code"
        extra = body["extra"]
        assert (extra["kind"], extra["stack"], extra["repository"]) == ("flag", "web", "org/web")
        assert extra["source"] == {"file": ".ph/flags.ts", "export": "beta"}
        assert extra["fields"] == ["name"]
        self.flag.refresh_from_db()
        assert self.flag.name == "Beta"

    @parameterized.expand(
        [
            ("unowned_field", {"active": False}),
            ("owned_field_unchanged", {"name": "Beta", "active": False}),
        ]
    )
    def test_writes_code_does_not_own_are_allowed(self, _name: str, body: dict[str, Any]) -> None:
        response = self.patch_flag(body)

        assert response.status_code == status.HTTP_200_OK, response.json()

    @parameterized.expand([("true", True), ("string", "true"), ("number", 1)])
    def test_a_soft_delete_is_refused_even_when_code_owns_no_field(self, _name: str, deleted: Any) -> None:
        StackBinding.all_teams.using("stacks_db_writer").filter(id=self.binding.id).update(owned_fields=[])
        cache.clear()

        response = self.patch_flag({"deleted": deleted})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "managed_in_code"
        assert response.json()["extra"]["binding_id"] == str(self.binding.id)

    def _push_token(self, *, live: bool, stack: Stack | None = None) -> str:
        """A stacks token, recorded as the token of a running push of `stack` that holds its lease or lost it."""
        stack = stack or self.stack
        token, _ = credentials.mint(
            user=self.user, target_team_id=self.team.id, scopes=["feature_flag:read", "feature_flag:write"]
        )
        attempt = uuid4()
        Stack.all_teams.using("stacks_db_writer").filter(id=stack.id).update(
            lease_attempt_id=attempt,
            lease_generation=1,
            lease_expires_at=timezone.now() + (timedelta(minutes=3) if live else -timedelta(seconds=1)),
        )
        StackDiff.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            stack=stack,
            target_team_id=self.team.id,
            encrypted_description=b"",
            description_hash="",
            status="running",
            expires_at=timezone.now() + timedelta(hours=1),
            deadline_at=timezone.now() + timedelta(hours=1),
            push_attempt_id=attempt,
            push_generation=1,
            push_status="running",
            push_token_id=token.id,
        )
        return token.token

    def test_only_the_running_push_of_the_managing_stack_may_write(self) -> None:
        other = Stack.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id, target_team_id=self.team.id, name="other", organization_id=str(self.organization.id)
        )
        idle, _ = credentials.mint(
            user=self.user, target_team_id=self.team.id, scopes=["feature_flag:read", "feature_flag:write"]
        )
        expired = self._push_token(live=False)
        foreign = self._push_token(live=True, stack=other)
        live = self._push_token(live=True)
        self.client.logout()

        def patch_as(token: str, name: str) -> int:
            return self.patch_flag({"name": name}, HTTP_AUTHORIZATION=f"Bearer {token}").status_code

        assert patch_as(idle.token, "Not a push") == status.HTTP_409_CONFLICT
        assert patch_as(expired, "Lease lost") == status.HTTP_409_CONFLICT
        assert patch_as(foreign, "Another stack") == status.HTTP_409_CONFLICT
        assert patch_as(live, "Pushed from code") == status.HTTP_200_OK

    def test_a_detached_entity_is_writable(self) -> None:
        StackBinding.all_teams.using("stacks_db_writer").filter(id=self.binding.id).update(status="detached")

        assert self.patch_flag({"name": "Back in the UI"}).status_code == status.HTTP_200_OK

    def test_a_project_with_no_stack_pays_one_stacks_query_per_marker_lifetime(self) -> None:
        StackBinding.all_teams.using("stacks_db_writer").all().delete()
        Stack.all_teams.using("stacks_db_writer").all().delete()
        cache.clear()

        with self.assertNumQueries(1, using="stacks_db_writer"):
            first = self.patch_flag({"name": "Renamed"})
        with self.assertNumQueries(0, using="stacks_db_writer"):
            second = self.patch_flag({"name": "Renamed again"})

        assert (first.status_code, second.status_code) == (status.HTTP_200_OK, status.HTTP_200_OK)

    def test_an_evicted_marker_is_read_from_the_stacks_database(self) -> None:
        cache.clear()

        assert self.patch_flag({"name": "Slipped through"}).status_code == status.HTTP_409_CONFLICT

    def test_a_cache_outage_falls_back_to_the_stacks_database(self) -> None:
        unmanaged = FeatureFlag.objects.create(team=self.team, key="other", name="Other", created_by=self.user)
        broken = MagicMock()
        broken.get.side_effect = broken.set.side_effect = ConnectionError("redis down")
        # Only the write lock's cache breaks, so the rest of the request still runs.
        with patch.object(managed, "cache", broken):
            refused = self.patch_flag({"name": "Renamed"})
            allowed = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{unmanaged.id}/", {"name": "Fine"}, format="json"
            )

        assert refused.status_code == status.HTTP_409_CONFLICT
        assert allowed.status_code == status.HTTP_200_OK, allowed.json()


def _routed_viewsets() -> set[type]:
    found: set[type] = set()
    pending: list[Any] = list(get_resolver().url_patterns)
    while pending:
        pattern = pending.pop()
        if isinstance(pattern, URLResolver):
            pending.extend(pattern.url_patterns)
        elif isinstance(pattern, URLPattern):
            view_class = getattr(pattern.callback, "cls", None)
            if view_class is not None:
                found.add(view_class)
    return found


def _queryset_label(view_class: type) -> str | None:
    queryset = getattr(view_class, "queryset", None)
    model = getattr(queryset, "model", None)
    return model._meta.label if model is not None else None


def _contract_label(view_class: type) -> str | None:
    owner = next((cls for cls in view_class.__mro__ if "read_object" in cls.__dict__), None)
    if owner is None or not owner.__module__.startswith("products."):
        return None
    returned = str(inspect.signature(owner.__dict__["read_object"]).return_annotation)
    name = returned.split("|")[0].strip().rsplit(".", 1)[-1]
    return f"{owner.__module__.split('.')[1]}.{name}"


class TestEveryManagedKindIsGuarded:
    @parameterized.expand(sorted(managed.KIND_BY_MODEL.items()))
    def test_the_kinds_write_routes_run_the_guard(self, label: str, kind: str) -> None:
        assert label in guarded_model_labels()
        try:
            apps.get_model(label)
        except LookupError:
            viewsets = [view for view in _routed_viewsets() if _contract_label(view) == label]
        else:
            # A subclass such as the enterprise event definition is served by its parent's viewsets.
            model = apps.get_model(label)
            labels = {label, *(parent._meta.label for parent in model._meta.get_parent_list())}
            viewsets = [view for view in _routed_viewsets() if _queryset_label(view) in labels]
        if kind in UNGUARDED_KINDS:
            return
        assert viewsets, f"no routed viewset loads {label} through a queryset"
        for view in viewsets:
            assert issubclass(view, TeamAndOrgViewSetMixin), f"{view.__name__} skips the managed write permission"
