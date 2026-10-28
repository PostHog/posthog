import json
import base64
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQueryResponse

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import PersonalAPIKey, PropertyDefinition, Team
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    revoke_application_sessions,
    revoke_oauth_session,
    revoke_oauth_token_session,
)
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.actions.backend.models.action import Action
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.mcp_events.backend.facade.contracts import MCPCallbackError
from products.mcp_events.backend.models import MCPEventSubscription
from products.mcp_events.backend.tasks.tasks import expire_mcp_event_subscriptions, reconcile_mcp_event_subscriptions

ACCESS_CONTROLS_SUPPORTED = (
    "products.access_control.backend.facade.user_access_control.UserAccessControl.access_controls_supported"
)
RBAC_SUPPORTED = "products.access_control.backend.facade.user_access_control.UserAccessControl.rbac_supported"


class MCPEventSubscriptionTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_mock = self.enterContext(
            patch("products.mcp_events.backend.presentation.views.posthoganalytics.feature_enabled", return_value=True)
        )
        self.verify_callback = self.enterContext(
            patch("products.mcp_events.backend.logic.subscriptions.verify_callback")
        )
        self.key = self.create_personal_api_key_with_scopes(["mcp_event_subscription:write", "query:read"])
        self.client.logout()
        self.authorization = f"Bearer {self.key}"
        self.url = f"/api/projects/{self.team.pk}/mcp_event_subscriptions/"
        self.callback_url = "https://example.com/callback"
        self.secret = "whsec_" + base64.b64encode(b"a" * 32).decode()
        self.filters: dict[str, Any] = {"events": [{"id": "example_event", "type": "events"}]}

    def payload(self) -> dict[str, Any]:
        return {
            "name": "posthog.event_captured",
            "arguments": {"project_id": self.team.pk, "filters": self.filters},
            "delivery": {"mode": "webhook", "url": self.callback_url, "secret": self.secret},
        }

    def post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        return self.client.post(self.url + endpoint + "/", payload, HTTP_AUTHORIZATION=self.authorization)

    def subscribe(self) -> MCPEventSubscription:
        response = self.post("subscribe", self.payload())
        self.assertEqual(response.status_code, 200, response.json())
        self.assertNotIn(self.secret, json.dumps(response.json()))
        return MCPEventSubscription.objects.for_team(self.team.pk).get(id=response.json()["id"])

    def unsubscribe(self) -> None:
        payload = self.payload()
        payload["delivery"].pop("secret")
        response = self.post("unsubscribe", payload)
        self.assertEqual(response.status_code, 200, response.json())

    def destination(self, subscription: MCPEventSubscription) -> HogFunction:
        assert subscription.hog_function_id is not None
        return HogFunction.objects.get(pk=subscription.hog_function_id)

    def assert_delivering(self, subscription: MCPEventSubscription, delivering: bool) -> None:
        subscription.refresh_from_db()
        function = self.destination(subscription)
        self.assertEqual(subscription.active, delivering)
        self.assertEqual(function.enabled, delivering)
        self.assertEqual(bool(function.encrypted_inputs), delivering)

    def restrict_event_property(self, name: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=name, property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")


class TestMCPEventSubscriptionAPI(MCPEventSubscriptionTestCase):
    def test_subscribe_creates_a_signed_managed_destination(self) -> None:
        subscription = self.subscribe()
        self.assertTrue(
            any(call.args[:2] == ("mcp-events", self.user.distinct_id) for call in self.flag_mock.mock_calls)
        )
        function = self.destination(subscription)
        self.assertEqual(function.managed_by, "mcp_events")
        self.assertTrue(function.enabled)
        self.assertEqual((function.filters or {})["events"], self.filters["events"])
        encrypted_inputs = function.encrypted_inputs or {}
        self.assertEqual(encrypted_inputs["signing_secret"]["value"], self.secret)
        self.assertEqual(encrypted_inputs["url"]["value"], self.callback_url)
        self.assert_delivering(subscription, True)

    def test_subscription_cannot_be_accessed_by_another_owner(self) -> None:
        subscription = self.subscribe()
        self.client.force_login(self._create_user("other@example.com"))
        self.assertEqual(self.client.get(self.url + str(subscription.pk) + "/").status_code, 404)

    @parameterized.expand(
        [
            ("preview", "unsupported_global = 'value'", "Real-time filters cannot read"),
            ("subscribe", "unsupported_global = 'value'", "Real-time filters cannot read"),
            ("preview", "typeof(properties.rating) = 'integer'", "This filter cannot be previewed"),
            ("subscribe", "typeof(properties.rating) = 'integer'", "This filter cannot be previewed"),
        ]
    )
    def test_invalid_realtime_filters_cannot_preview_or_subscribe(
        self, endpoint: str, expression: str, message: str
    ) -> None:
        self.filters = {"properties": [{"type": "hogql", "key": expression}]}
        payload = self.payload() if endpoint == "subscribe" else self.payload()["arguments"]
        response = self.post(endpoint, payload)
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn(message, json.dumps(response.json()))
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    @parameterized.expand(
        [(endpoint, location) for endpoint in ("preview", "subscribe") for location in ("actions", "events")]
    )
    @patch(ACCESS_CONTROLS_SUPPORTED, True)
    def test_action_access_is_required_at_setup(self, endpoint: str, location: str) -> None:
        action = Action.objects.create(
            team=self.team, name="Example action", steps_json=[{"event": "example_event"}], created_by=self.user
        )
        self.user = self._create_user("subscriber@example.com")
        self.authorization = (
            f"Bearer {self.create_personal_api_key_with_scopes(['mcp_event_subscription:write', 'query:read'])}"
        )
        self.filters = {location: [{"id": str(action.pk), "type": "actions"}]}
        AccessControl.objects.create(team=self.team, resource="action", resource_id=str(action.pk), access_level="none")
        response = self.post(endpoint, self.payload() if endpoint == "subscribe" else self.payload()["arguments"])
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("viewer access", json.dumps(response.json()))
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())

    def test_filter_cannot_read_a_restricted_property(self) -> None:
        self.restrict_event_property("$feature/secret")
        self.filters = {"properties": [{"key": "$active_feature_flags", "type": "event", "operator": "is_set"}]}
        response = self.post("subscribe", self.payload())
        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    def test_subscriptions_remain_isolated_between_child_environments(self) -> None:
        parent = self.team
        children = [
            Team.objects.create(organization=self.organization, project=parent.project, parent_team=parent, name=name)
            for name in ("Staging", "Preview")
        ]
        subscriptions = []
        for child in children:
            self.team = child
            self.url = f"/api/projects/{child.pk}/mcp_event_subscriptions/"
            subscription = self.subscribe()
            self.assertEqual(subscription.team_id, child.pk)
            self.assertEqual(self.destination(subscription).team_id, child.pk)
            subscriptions.append(subscription)
        page = self.client.get(self.url, HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual([row["id"] for row in page.json()["results"]], [str(subscriptions[-1].pk)])
        sibling = self.client.get(self.url + str(subscriptions[0].pk) + "/", HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(sibling.status_code, 404, sibling.json())

    def test_list_pages_keep_all_subscriptions_with_tied_creation_times(self) -> None:
        first = self.subscribe()
        self.filters = {"events": [{"id": "second_event", "type": "events"}]}
        second = self.subscribe()
        MCPEventSubscription.objects.for_team(self.team.pk).filter(id__in=[first.pk, second.pk]).update(
            created_at=timezone.now()
        )
        page = self.client.get(self.url + "?limit=1", HTTP_AUTHORIZATION=self.authorization).json()
        self.assertEqual(page["count"], 2)
        next_page = self.client.get(page["next"], HTTP_AUTHORIZATION=self.authorization).json()
        rows = page["results"] + next_page["results"]
        self.assertEqual([row["id"] for row in rows], sorted([str(first.pk), str(second.pk)], reverse=True))
        self.assertIsNone(next_page["next"])

    @parameterized.expand(["personal_api_key", "oauth"])
    def test_delegated_credentials_cannot_create_long_lived_subscriptions(self, source: str) -> None:
        claims: dict[str, str | int] = {"id": self.user.pk}
        if source == "personal_api_key":
            claims["personal_api_key_id"] = PersonalAPIKey.objects.get(user=self.user).pk
        else:
            token = OAuthAccessToken.objects.create(
                user=self.user,
                application=self.oauth_application(),
                token="pha_mcp_delegated_test",
                scope="mcp_event_subscription:write query:read",
                expires=timezone.now() + timedelta(hours=1),
                scoped_teams=[self.team.pk],
            )
            claims["oauth_access_token_id"] = str(token.pk)
        self.authorization = f"Bearer {encode_jwt(claims, timedelta(minutes=5), PosthogJwtAudience.DELEGATED_USER)}"
        response = self.post("subscribe", self.payload())
        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())

    def oauth_application(self) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name="MCP events test",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )

    @parameterized.expand(
        ["disconnect", "application_scope_change", "delete_application", "revoke_last_token", "revoke_one_of_two"]
    )
    def test_oauth_refresh_keeps_identity_and_bounds_lifetime_by_token_expiry(self, final_change: str) -> None:
        application = self.oauth_application()
        expiry = timezone.now() + timedelta(hours=1)
        tokens = [
            OAuthAccessToken.objects.create(
                user=self.user,
                application=application,
                token=f"pha_mcp_events_test_{index}",
                scope="mcp_event_subscription:write query:read",
                expires=expiry + timedelta(hours=index),
                scoped_teams=[self.team.pk],
            )
            for index in range(2)
        ]
        self.authorization = f"Bearer {tokens[0].token}"
        first = self.subscribe()
        self.assertEqual(first.expires_at, tokens[0].expires)
        self.authorization = f"Bearer {tokens[1].token}"
        refreshed = self.subscribe()
        self.assertEqual(
            (first.pk, first.generation, first.hog_function_id),
            (refreshed.pk, refreshed.generation, refreshed.hog_function_id),
        )
        self.assertEqual(refreshed.expires_at, tokens[1].expires)
        with transaction.atomic():
            if final_change == "revoke_one_of_two":
                revoke_oauth_token_session(access_token=tokens[0])
            else:
                tokens[0].delete()
        self.assert_delivering(refreshed, True)
        if final_change == "disconnect":
            revoke_oauth_session(access_token=tokens[1])
        elif final_change == "application_scope_change":
            revoke_application_sessions(application)
        elif final_change in ("revoke_last_token", "revoke_one_of_two"):
            revoke_oauth_token_session(access_token=tokens[1])
        else:
            application.delete()
        self.assert_delivering(refreshed, False)

    @parameterized.expand(["preview", "subscribe"])
    def test_malformed_event_filter_is_rejected_before_callback(self, endpoint: str) -> None:
        self.filters = {"events": [{"id": "example_event"}]}
        response = self.post(endpoint, self.payload() if endpoint == "subscribe" else self.payload()["arguments"])
        self.assertEqual(response.status_code, 400, response.json())
        self.verify_callback.assert_not_called()
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    def test_preview_concurrency_limit_returns_a_throttled_response(self) -> None:
        with patch(
            "posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner.run",
            side_effect=ConcurrencyLimitExceeded("example concurrency limit"),
        ):
            response = self.post("preview", self.payload()["arguments"])
        self.assertEqual(response.status_code, 429, response.json())

    def test_query_only_key_can_preview_without_creating_subscription(self) -> None:
        self.authorization = f"Bearer {self.create_personal_api_key_with_scopes(['query:read'])}"
        with patch(
            "posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner.run", return_value=HogQLQueryResponse(results=[])
        ):
            response = self.post("preview", self.payload()["arguments"])
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["examples"], [])
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())


class TestMCPEventSubscriptionLifecycle(MCPEventSubscriptionTestCase):
    def test_callback_failure_leaves_no_subscription_or_destination(self) -> None:
        self.verify_callback.side_effect = MCPCallbackError("timeout")
        response = self.post("subscribe", self.payload())
        self.assertEqual(response.status_code, 400, response.json())
        self.assertEqual(response.json()["attr"], "callback__reason")
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    @parameterized.expand(
        ["delete_key", "roll_key", "drop_scope", "remove_member", "deactivate_user", "restrict_property"]
    )
    def test_setup_rechecks_access_after_callback_verification(self, change: str) -> None:
        self.filters["properties"] = [{"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"}]

        def change_access(**kwargs: object) -> None:
            key = PersonalAPIKey.objects.get(user=self.user)
            if change == "delete_key":
                key.delete()
            elif change == "roll_key":
                key.last_rolled_at = timezone.now()
                key.save()
            elif change == "drop_scope":
                key.scopes = ["query:read"]
                key.save()
            elif change == "remove_member":
                self.organization_membership.delete()
            elif change == "deactivate_user":
                self.user.is_active = False
                self.user.save(update_fields=["is_active"])
            else:
                self.restrict_event_property("plan")

        self.verify_callback.side_effect = change_access
        response = self.post("subscribe", self.payload())
        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    @parameterized.expand(["renew", "stop", "expire"])
    def test_lifecycle_keeps_one_destination_in_step_with_the_subscription(self, operation: str) -> None:
        subscription = self.subscribe()
        if operation == "renew":
            self.secret = "whsec_" + base64.b64encode(b"b" * 32).decode()
            renewed = self.subscribe()
            self.assertEqual((renewed.pk, renewed.hog_function_id), (subscription.pk, subscription.hog_function_id))
            function = self.destination(subscription)
            self.assertEqual((function.encrypted_inputs or {})["signing_secret"]["value"], self.secret)
        elif operation == "stop":
            self.unsubscribe()
        else:
            MCPEventSubscription.objects.for_team(self.team.pk).filter(pk=subscription.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1)
            )
            expire_mcp_event_subscriptions()
        self.assert_delivering(subscription, operation == "renew")
        self.assertEqual(HogFunction.objects.filter(team=self.team).count(), 1)

    def test_stop_works_after_a_filtered_action_is_deleted(self) -> None:
        action = Action.objects.create(
            team=self.team, name="Example action", steps_json=[{"event": "example_event"}], created_by=self.user
        )
        self.filters = {"actions": [{"id": action.pk, "type": "actions"}]}
        subscription = self.subscribe()
        action.delete()
        self.unsubscribe()
        self.assert_delivering(subscription, False)


class TestMCPEventSubscriptionRevocation(MCPEventSubscriptionTestCase):
    @parameterized.expand(
        ["delete_key", "roll_key", "drop_scope", "scope_other_team", "remove_member", "deactivate_user", "expire_key"]
    )
    def test_credential_and_membership_changes_stop_delivery(self, change: str) -> None:
        subscription = self.subscribe()
        key = PersonalAPIKey.objects.get(user=self.user)
        if change == "delete_key":
            key.delete()
        elif change == "roll_key":
            key.last_rolled_at = timezone.now()
            key.save()
        elif change == "drop_scope":
            key.scopes = ["mcp_event_subscription:write"]
            key.save()
        elif change == "scope_other_team":
            key.scoped_teams = [self.team.pk + 1]
            key.save()
        elif change == "deactivate_user":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        elif change == "expire_key":
            key.expires_at = timezone.now() - timedelta(seconds=1)
            key.save()
        else:
            self.organization_membership.delete()
        self.assert_delivering(subscription, False)

    def test_key_use_does_not_stop_delivery(self) -> None:
        subscription = self.subscribe()
        key = PersonalAPIKey.objects.get(user=self.user)
        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at"])
        self.assert_delivering(subscription, True)

    @parameterized.expand(["member", "role"])
    @patch(ACCESS_CONTROLS_SUPPORTED, True)
    @patch(RBAC_SUPPORTED, True)
    def test_losing_action_access_stops_delivery(self, target: str) -> None:
        action = Action.objects.create(
            team=self.team, name="Example action", steps_json=[{"event": "example_event"}], created_by=None
        )
        self.filters = {"actions": [{"id": str(action.pk), "type": "actions"}]}
        subscription = self.subscribe()
        if target == "member":
            with self.captureOnCommitCallbacks(execute=True):
                AccessControl.objects.create(
                    team=self.team,
                    resource="action",
                    resource_id=str(action.pk),
                    access_level="none",
                    organization_member=self.organization_membership,
                )
        else:
            role = Role.objects.create(organization=self.organization, name="Restricted")
            with self.captureOnCommitCallbacks(execute=True):
                AccessControl.objects.create(
                    team=self.team, resource="action", resource_id=str(action.pk), access_level="none", role=role
                )
            self.assert_delivering(subscription, True)
            with self.captureOnCommitCallbacks(execute=True):
                RoleMembership.objects.create(
                    role=role, user=self.user, organization_member=self.organization_membership
                )
        self.assert_delivering(subscription, False)

    @parameterized.expand([("filtered_property", False), ("unrelated_property", True)])
    def test_property_restrictions_revalidate_live_subscriptions(self, _name: str, still_delivering: bool) -> None:
        self.filters = {
            "events": [{"id": "example_event", "type": "events"}],
            "properties": [{"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"}],
        }
        subscription = self.subscribe()
        with self.captureOnCommitCallbacks(execute=True):
            self.restrict_event_property("email" if still_delivering else "plan")
        self.assert_delivering(subscription, still_delivering)
        if still_delivering:
            self.assertEqual(subscription.restricted_properties, ["email"])
            function = self.destination(subscription)
            self.assertIn("email", (function.inputs or {})["restricted_properties"]["value"]["names"])

    @parameterized.expand(["subscription", "user"])
    def test_deletion_disables_the_surviving_destination(self, target: str) -> None:
        subscription = self.subscribe()
        function = self.destination(subscription)
        if target == "subscription":
            subscription.delete()
        else:
            self.user.delete()
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        function.refresh_from_db()
        self.assertFalse(function.enabled)
        self.assertIsNone(function.encrypted_inputs)

    def test_membership_demotion_refreshes_redaction_after_commit(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.restrict_event_property("email")
        subscription = self.subscribe()
        self.assertNotIn("email", subscription.restricted_properties)
        with self.captureOnCommitCallbacks(execute=True):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save(update_fields=["level"])
        self.assert_delivering(subscription, True)
        self.assertIn("email", subscription.restricted_properties)

    @parameterized.expand(["action", "test_account"])
    def test_changed_saved_filters_recheck_property_access(self, target: str) -> None:
        self.restrict_event_property("secret")
        action = Action.objects.create(
            team=self.team, name="Example action", steps_json=[{"event": "example_event"}], created_by=self.user
        )
        self.filters = {"actions": [{"id": str(action.pk), "type": "actions"}], "filter_test_accounts": True}
        subscription = self.subscribe()
        properties = [{"type": "event", "key": "secret", "operator": "exact", "value": "private"}]
        with self.captureOnCommitCallbacks(execute=True):
            if target == "action":
                action.steps_json = [{"event": "example_event", "properties": properties}]
                action.save()
            else:
                self.team.test_account_filters = properties
                self.team.save(update_fields=["test_account_filters"])
        self.assert_delivering(subscription, False)

    def test_allowed_action_change_updates_the_managed_predicate(self) -> None:
        action = Action.objects.create(
            team=self.team, name="Example action", steps_json=[{"event": "first_event"}], created_by=self.user
        )
        self.filters = {"actions": [{"id": str(action.pk), "type": "actions"}]}
        subscription = self.subscribe()
        previous = self.destination(subscription).filters
        with self.captureOnCommitCallbacks(execute=True):
            action.steps_json = [{"event": "second_event"}]
            action.save()
        self.assert_delivering(subscription, True)
        self.assertNotEqual(self.destination(subscription).filters, previous)

    def test_reconciliation_repairs_a_missed_access_change_job(self) -> None:
        self.filters["properties"] = [{"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"}]
        subscription = self.subscribe()
        with patch("products.mcp_events.backend.signals.revalidate_mcp_event_subscriptions.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self.restrict_event_property("plan")
        self.assert_delivering(subscription, True)
        reconcile_mcp_event_subscriptions()
        self.assert_delivering(subscription, False)

    @parameterized.expand([False, True])
    def test_revalidation_jobs_coalesce_without_surviving_a_rolled_back_savepoint(self, rollback_first: bool) -> None:
        self.subscribe()
        with patch("products.mcp_events.backend.signals.revalidate_mcp_event_subscriptions.delay") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                if rollback_first:
                    try:
                        with transaction.atomic():
                            self.restrict_event_property("rolled_back")
                            raise ValueError("Rollback the filter change")
                    except ValueError:
                        pass
                self.restrict_event_property("first")
                self.restrict_event_property("second")
            dispatch.assert_called_once_with(self.team.pk)
