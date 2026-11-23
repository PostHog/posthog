"""The run's authority after admission: the credential that asked, the lease, and who may change a binding."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import exceptions, status

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey

from products.stacks.backend.logic import credentials, lease, stacks
from products.stacks.backend.models import Stack, StackBinding, StackDiff
from products.stacks.backend.presentation import views
from products.stacks.backend.tests.base import StackAPITestBase, resource

SOURCE = resource("source", "billing", password={"$secret": "DB_PASSWORD"})


class TestTheAdmittingCredential(StackAPITestBase):
    def _key_diff(self, scopes: list[str]) -> tuple[dict[str, Any], PersonalAPIKey]:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        response = self.start_diff([resource("insight", "signups")], HTTP_AUTHORIZATION=f"Bearer {key}")
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        return response.json(), PersonalAPIKey.objects.get(user=self.user)

    def test_a_key_that_lost_a_scope_after_admission_stops_the_run(self) -> None:
        diff, key = self._key_diff(["stack:read", "insight:read"])
        key.scopes = ["stack:read"]
        key.save()

        self.run_diff(diff["id"])

        error = (StackDiff.all_teams.get(id=diff["id"]).diff or {})["errors"][0]
        assert error["code"] == "caller_unavailable"
        assert "insight:read" in error["message"]
        assert self.engine.credentials == []

    def test_the_run_token_never_outlives_the_key(self) -> None:
        diff, key = self._key_diff(["stack:read", "insight:read"])
        key.expires_at = timezone.now() + timedelta(minutes=5)
        key.save()

        self.run_diff(diff["id"])

        assert self.engine.token_expiries[0] <= key.expires_at

    def test_an_expired_key_stops_the_run(self) -> None:
        diff, key = self._key_diff(["stack:read", "insight:read"])
        PersonalAPIKey.objects.filter(id=key.id).update(expires_at=timezone.now() - timedelta(seconds=1))

        self.run_diff(diff["id"])

        assert (StackDiff.all_teams.get(id=diff["id"]).diff or {})["errors"][0]["code"] == "caller_unavailable"

    def test_a_credential_the_worker_cannot_recheck_is_refused_at_admission(self) -> None:
        request: Any = SimpleNamespace(successful_authenticator=object(), META={})

        with pytest.raises(exceptions.PermissionDenied) as refused:
            views._grant(request)

        assert refused.value.get_codes() == "credential_not_supported"


class TestTheLease(StackAPITestBase):
    def test_an_expired_lease_is_never_extended(self) -> None:
        diff = self.ready_diff([resource("insight", "a")])
        self.push(diff["id"])
        stack = Stack.all_teams.get()
        expired = timezone.now() - timedelta(seconds=1)
        Stack.all_teams.update(lease_expires_at=expired)

        assert stack.lease_attempt_id is not None
        assert not lease.extend(stack.team_id, stack.id, stack.lease_attempt_id, stack.lease_generation)
        assert Stack.all_teams.get().lease_expires_at == expired

    def test_a_takeover_between_mint_and_registration_withdraws_the_token_before_the_engine_runs(self) -> None:
        diff = self.ready_diff([resource("insight", "a")])
        self.push(diff["id"])
        mint = credentials.mint

        def mint_then_lose_the_lease(**kwargs: Any):
            minted = mint(**kwargs)
            # The worker paused here, and the lease expired and was taken over meanwhile.
            Stack.all_teams.update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            self.sweep()
            return minted

        with patch("products.stacks.backend.logic.runs.credentials.mint", mint_then_lose_the_lease):
            self.run_push(diff["id"])

        assert self.engine.remote.of("insight") == {}
        assert not OAuthAccessToken.objects.filter(application__client_id=credentials.STACKS_OAUTH_CLIENT_ID).exists()
        assert self.get_diff(diff["id"])["push_status"] == "uncertain"

    def test_a_refused_push_keeps_the_takeover_it_caused(self) -> None:
        running = self.ready_diff([resource("insight", "a")])
        self.push(running["id"])
        Stack.all_teams.update(lease_expires_at=timezone.now() - timedelta(seconds=1))

        response = self.push(running["id"])

        # The push is refused, because the takeover made the stack uncertain, and the takeover stays.
        assert response.json()["code"] in {"push_uncertain", "stack_moved"}
        stack = Stack.all_teams.get()
        assert stack.lease_attempt_id is None
        assert stack.needs_reconcile
        assert self.get_diff(running["id"])["push_status"] == "uncertain"

    def test_detach_reads_the_binding_again_under_the_lock(self) -> None:
        self.pushed([resource("insight", "a")])
        bound = StackBinding.all_teams.get()
        stale = StackBinding.all_teams.get(id=bound.id)
        stale.status = "pending"

        with patch("products.stacks.backend.logic.stacks.get_binding", return_value=stale):
            stacks.detach(self.team.id, "web", bound.id)

        # The binding was bound under the lock, so it stays as a detached marker instead of being deleted.
        assert StackBinding.all_teams.get(id=bound.id).status == "detached"


class TestProvisioning(StackAPITestBase):
    def test_a_row_that_is_not_the_stacks_application_is_never_changed(self) -> None:
        OAuthApplication.objects.filter(client_id=credentials.STACKS_OAUTH_CLIENT_ID).delete()
        OAuthApplication.objects.create(
            client_id=credentials.STACKS_OAUTH_CLIENT_ID,
            name="Squatter",
            client_type="public",
            authorization_grant_type="authorization-code",
            redirect_uris=credentials.STACKS_OAUTH_REDIRECT_URI,
            algorithm="RS256",
            is_first_party=True,
            scopes=["feature_flag:read"],
        )

        with pytest.raises(credentials.CallerUnavailable):
            credentials.provision_stacks_oauth_app()

        assert OAuthApplication.objects.get(client_id=credentials.STACKS_OAUTH_CLIENT_ID).scopes == [
            "feature_flag:read"
        ]


class TestSecretsAndClaims(StackAPITestBase):
    def test_a_secret_changed_while_a_diff_computes_leaves_that_diff_unpushable(self) -> None:
        self.call("put", "web/secrets/DB_PASSWORD/", {"value": "old-value"})
        self.engine.during_diff = lambda: self.call("put", "web/secrets/DB_PASSWORD/", {"value": "new-value"})

        diff = self.ready_diff([SOURCE])

        assert diff["status"] == "stale"

    def test_a_secret_removed_after_the_diff_is_refused_at_push(self) -> None:
        self.call("put", "web/secrets/DB_PASSWORD/", {"value": "old-value"})
        diff = self.ready_diff([SOURCE])
        self.call("delete", "web/secrets/DB_PASSWORD/")

        assert self.push(diff["id"]).json()["code"] == "stack_moved"

    def test_redaction_never_rewrites_an_identity(self) -> None:
        self.call("put", "web/secrets/DB_PASSWORD/", {"value": "billing"})

        diff = self.ready_diff([SOURCE])

        [change] = diff["diff"]["changes"]
        assert (change["kind"], change["key"]) == ("source", "billing")
        assert change["name"] == "[redacted]"

    def test_two_stacks_cannot_both_create_one_natural_key(self) -> None:
        first = self.ready_diff([resource("flag", "beta", key="beta")])
        second = self.ready_diff([resource("flag", "beta", key="beta")], stack="app")

        assert self.push(first["id"]).status_code == status.HTTP_202_ACCEPTED
        refused = self.push(second["id"], stack="app")

        assert refused.status_code == status.HTTP_409_CONFLICT
        assert refused.json()["code"] == "claimed_by_other_stack"
        self.run_push(first["id"])
        assert len(self.engine.remote.of("flag")) == 1
