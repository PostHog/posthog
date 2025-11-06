from typing import Any

from unittest import mock
from unittest.mock import Mock, patch

from django.db import IntegrityError
from django.test import TestCase

from parameterized import parameterized
from rest_framework import exceptions
from rest_framework.exceptions import NotFound, ValidationError

from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.models.user import User

from products.enterprise.backend.api.vercel.types import VercelUserClaims
from products.enterprise.backend.vercel.integration import VercelIntegration


class TestVercelIntegration(TestCase):
    TEST_INSTALLATION_ID = "icfg_9bceb8ccT32d3U417ezb5c8p"
    NONEXISTENT_INSTALLATION_ID = "icfg_nonexistent123456789012"
    NEW_INSTALLATION_ID = "icfg_987654321abcdef123456789"
    DIFFERENT_INSTALLATION_ID = "icfg_different123456789012345"

    def make_team_with_vercel(self, org, user):
        team = Team.objects.create(organization=org, name="Test Team")
        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "Test Resource"},
            created_by=user,
        )
        return team, resource

    def make_feature_flag(self, team, name, description, archived):
        # archived maps to the deleted field in FeatureFlag model
        return FeatureFlag.objects.create(
            team=team,
            key=name,
            name=description,
            deleted=archived,
        )

    def make_experiment(self, team, name, description, archived):
        ff = FeatureFlag.objects.create(team=team, key="exp-flag")
        return Experiment.objects.create(
            team=team,
            name=name,
            description=description,
            archived=archived,
            feature_flag=ff,
        )

    def assert_vercel_item(
        self, item, result, category, is_archived, slug=None, expected_name=None, expected_description=None
    ):
        assert result["id"] == f"{category}_{item.pk}"
        assert result["slug"] == slug or item.name.lower().replace(" ", "-")
        assert result["name"] == expected_name or getattr(item, "key", item.name)
        assert result["description"] == expected_description or getattr(item, "description", item.name)
        assert result["category"] == category
        assert result["isArchived"] == is_archived
        assert "origin" in result
        assert "createdAt" in result
        assert "updatedAt" in result
        # Verify createdAt is in milliseconds (should be > 1 billion ms since epoch)
        assert (
            result["createdAt"] > 1_000_000_000_000
        ), f"createdAt should be in milliseconds, got {result['createdAt']}"
        assert isinstance(result["createdAt"], int), f"createdAt should be int, got {type(result['createdAt'])}"
        # Verify updatedAt is in milliseconds
        assert (
            result["updatedAt"] > 1_000_000_000_000
        ), f"updatedAt should be in milliseconds, got {result['updatedAt']}"
        assert isinstance(result["updatedAt"], int), f"updatedAt should be int, got {type(result['updatedAt'])}"

    def make_vercel_item(self, **overrides):
        base = {
            "id": "test_id",
            "slug": "test-slug",
            "origin": "https://example.com",
            "name": "Test Item",
            "category": "test",
            "description": "Test Description",
            "isArchived": False,
        }
        base.update(overrides)
        return base

    def setUp(self):
        self.installation_id = self.TEST_INSTALLATION_ID
        self.user = User.objects.create_user(email="test@example.com", password="testpass", first_name="Test")
        self.organization = Organization.objects.create(name="Test Org")
        self.user.join(organization=self.organization, level=OrganizationMembership.Level.OWNER)

        self.installation = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=self.installation_id,
            config={"billing_plan_id": "free", "scopes": ["read"]},
            created_by=self.user,
        )

        self.payload: dict[str, Any] = {
            "scopes": ["read", "write"],
            "acceptedPolicies": {"toc": "2024-02-28T10:00:00Z"},
            "credentials": {"access_token": "token", "token_type": "Bearer"},
            "account": {
                "name": "Test Account",
                "url": "https://example.com",
                "contact": {"email": "contact@example.com", "name": "John Doe"},
            },
        }

        # Create mock user claims for tests
        self.user_claims = self._create_user_claims("test_user_123")

    def _create_user_claims(self, user_id: str) -> VercelUserClaims:
        return VercelUserClaims(
            iss="https://marketplace.vercel.com",
            sub="account:test:user:test",
            aud="test_audience",
            account_id="test_account",
            installation_id=self.installation_id,
            user_id=user_id,
            user_role="ADMIN",
            type=None,
            user_avatar_url=None,
            user_email=self.payload["account"]["contact"]["email"],
            user_name=self.payload["account"]["contact"].get("name"),
        )

    def test_get_installation_exists(self):
        installation = VercelIntegration._get_installation(self.installation_id)
        assert installation.integration_id == self.installation_id
        assert installation.organization == self.organization

    def test_get_installation_not_found(self):
        with self.assertRaises(NotFound) as context:
            VercelIntegration._get_installation(self.NONEXISTENT_INSTALLATION_ID)
        assert str(context.exception) == "Installation not found"

    def test_get_vercel_plans_structure(self):
        plans = VercelIntegration.get_vercel_plans()
        assert len(plans) == 2

        free_plan = next(p for p in plans if p["id"] == "free")
        assert free_plan["type"] == "subscription"
        assert free_plan["name"] == "Free"
        assert not free_plan["paymentMethodRequired"]

        paid_plan = next(p for p in plans if p["id"] == "pay_as_you_go")
        assert paid_plan["type"] == "subscription"
        assert paid_plan["name"] == "Pay-as-you-go"
        assert paid_plan["paymentMethodRequired"]

    def test_get_installation_returns_free_plan(self):
        result = VercelIntegration.get_installation_billing_plan(self.installation_id)
        assert "billingplan" in result
        assert result["billingplan"]["id"] == "free"

    def test_update_installation_success(self):
        VercelIntegration.update_installation(self.installation_id, "pro200")

        updated_installation = OrganizationIntegration.objects.get(integration_id=self.installation_id)
        assert updated_installation.config["billing_plan_id"] == "free"

    def test_update_installation_not_found(self):
        VercelIntegration.update_installation(self.NONEXISTENT_INSTALLATION_ID, "pro200")

    @patch("django.conf.settings.DEBUG", True)
    def test_delete_installation_dev_mode(self):
        result = VercelIntegration.delete_installation(self.installation_id)

        assert result["finalized"]
        assert not OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists()

    @patch("django.conf.settings.DEBUG", False)
    def test_delete_installation_prod_mode(self):
        result = VercelIntegration.delete_installation(self.installation_id)

        assert not result["finalized"]
        assert not OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists()

    def test_delete_installation_not_found(self):
        with self.assertRaises(NotFound):
            VercelIntegration.delete_installation(self.NONEXISTENT_INSTALLATION_ID)

    def test_get_product_plans_posthog(self):
        result = VercelIntegration.get_product_plans("posthog")
        assert "plans" in result
        assert len(result["plans"]) == 2

    def test_get_product_plans_invalid_product(self):
        with self.assertRaises(NotFound) as context:
            VercelIntegration.get_product_plans("invalid_product")
        assert str(context.exception) == "Product not found"

    def test_upsert_installation_existing_installation(self):
        original_config = self.installation.config.copy()

        VercelIntegration.upsert_installation(self.installation_id, self.payload, self.user_claims)

        self.installation.refresh_from_db()
        assert self.installation.config == self.payload
        assert self.installation.config != original_config

    @patch("ee.vercel.integration.report_user_signed_up")
    def test_upsert_installation_new_user_new_org(self, mock_report):
        new_installation_id = self.NEW_INSTALLATION_ID
        new_user_claims = self._create_user_claims("new_user_456")
        new_user_claims.installation_id = new_installation_id
        new_user_claims.sub = "account:test:user:new"

        VercelIntegration.upsert_installation(new_installation_id, self.payload, new_user_claims)

        new_installation = OrganizationIntegration.objects.get(integration_id=new_installation_id)

        expected_config = self.payload.copy()
        expected_config["user_mappings"] = {"new_user_456": mock.ANY}

        # Check that user mapping was created
        assert "user_mappings" in new_installation.config
        assert "new_user_456" in new_installation.config["user_mappings"]
        assert new_installation.config["user_mappings"]["new_user_456"] is not None

        # Check all other config fields match
        for key, value in self.payload.items():
            assert new_installation.config[key] == value

        new_user = User.objects.get(email=self.payload["account"]["contact"]["email"])
        assert new_user.first_name == "John"
        assert not new_user.is_email_verified

        new_org = new_installation.organization
        assert new_org.name == self.payload["account"]["name"]

        membership = OrganizationMembership.objects.get(user=new_user, organization=new_org)
        assert membership.level == OrganizationMembership.Level.OWNER

        mock_report.assert_called_once()

    @patch("ee.vercel.integration.report_user_signed_up")
    def test_upsert_installation_existing_user_new_org(self, mock_report):
        existing_user = User.objects.create_user(
            email=self.payload["account"]["contact"]["email"], password="existing", first_name="Existing"
        )
        new_installation_id = self.NEW_INSTALLATION_ID
        existing_user_claims = self._create_user_claims("existing_user_789")
        existing_user_claims.installation_id = new_installation_id
        existing_user_claims.sub = "account:test:user:existing"

        VercelIntegration.upsert_installation(new_installation_id, self.payload, existing_user_claims)

        new_installation = OrganizationIntegration.objects.get(integration_id=new_installation_id)
        assert new_installation.created_by == existing_user

        # User mapping was not created for existing user (happens during SSO)
        assert "user_mappings" not in new_installation.config or "existing_user_789" not in new_installation.config.get(
            "user_mappings", {}
        )

        # Check all other config fields match
        for key, value in self.payload.items():
            assert new_installation.config[key] == value

        # Existing user was not automatically added to the organization (also happens during SSO)
        new_org = new_installation.organization
        assert not OrganizationMembership.objects.filter(user=existing_user, organization=new_org).exists()

        mock_report.assert_not_called()

    @patch("ee.vercel.integration.capture_exception")
    def test_upsert_installation_integrity_error(self, mock_capture):
        error_user_claims = self._create_user_claims("error_user_999")
        error_user_claims.installation_id = self.NEW_INSTALLATION_ID
        error_user_claims.sub = "account:test:user:error"

        with patch("ee.vercel.integration.OrganizationIntegration.objects.update_or_create") as mock_update_or_create:
            mock_update_or_create.side_effect = IntegrityError("Duplicate key")

            with self.assertRaises(ValidationError) as context:
                VercelIntegration.upsert_installation(self.NEW_INSTALLATION_ID, self.payload, error_user_claims)

            detail = context.exception.detail
            if isinstance(detail, dict):
                assert detail.get("validation_error") == "Something went wrong."
            mock_capture.assert_called_once()

    def test_upsert_installation_creates_org_with_fallback_name(self):
        new_installation_id = self.NEW_INSTALLATION_ID
        payload_without_name = self.payload.copy()
        del payload_without_name["account"]["name"]

        fallback_user_claims = self._create_user_claims("fallback_user_111")
        fallback_user_claims.installation_id = new_installation_id
        fallback_user_claims.sub = "account:test:user:fallback"
        fallback_user_claims.user_email = payload_without_name["account"]["contact"]["email"]
        fallback_user_claims.user_name = payload_without_name["account"]["contact"]["name"]

        VercelIntegration.upsert_installation(new_installation_id, payload_without_name, fallback_user_claims)

        new_installation = OrganizationIntegration.objects.get(integration_id=new_installation_id)
        assert new_installation.organization.name == f"Vercel Installation {new_installation_id}"

    def test_upsert_installation_creates_user_with_fallback_name(self):
        new_installation_id = self.NEW_INSTALLATION_ID
        payload_without_name = self.payload.copy()
        del payload_without_name["account"]["contact"]["name"]

        no_name_user_claims = self._create_user_claims("noname_user_222")
        no_name_user_claims.installation_id = new_installation_id
        no_name_user_claims.sub = "account:test:user:noname"
        no_name_user_claims.user_email = payload_without_name["account"]["contact"]["email"]
        no_name_user_claims.user_name = None

        VercelIntegration.upsert_installation(new_installation_id, payload_without_name, no_name_user_claims)

        new_user = User.objects.get(email=payload_without_name["account"]["contact"]["email"])
        assert new_user.first_name == payload_without_name["account"]["contact"]["email"].split("@")[0]

    def test_get_resource_not_found(self):
        with self.assertRaises(NotFound):
            VercelIntegration.get_resource("999999")

    def test_create_resource(self):
        resource_data = {
            "productId": "posthog",
            "name": "New Resource",
            "metadata": {"key": "value"},
            "billingPlanId": "free",
        }

        result = VercelIntegration.create_resource(self.installation_id, resource_data)

        assert "id" in result
        assert result["productId"] == "posthog"
        assert result["name"] == "New Resource"
        assert result["metadata"] == {"key": "value"}
        assert result["status"] == "ready"
        assert "secrets" in result
        assert "billingPlan" in result

        resource = Integration.objects.get(pk=result["id"])
        expected_config = {**resource_data, "externalId": None, "protocolSettings": None}
        assert resource.config == expected_config
        assert resource.team.organization == self.organization
        assert resource.created_by == self.installation.created_by

    def test_get_resource(self):
        team, resource = self.make_team_with_vercel(self.organization, self.user)
        resource.config["metadata"] = {}
        resource.save()

        result = VercelIntegration.get_resource(str(resource.pk))

        assert result["id"] == str(resource.pk)
        assert result["productId"] == "posthog"
        assert result["name"] == "Test Resource"
        assert result["status"] == "ready"
        assert "secrets" in result
        assert "billingPlan" in result

    def test_update_resource(self):
        team, resource = self.make_team_with_vercel(self.organization, self.user)
        resource.config.update(
            {
                "name": "Original Name",
                "metadata": {"old": "value"},
                "billingPlanId": "free",
            }
        )
        resource.save()

        update_data = {"name": "Updated Name", "metadata": {"new": "value"}}
        result = VercelIntegration.update_resource(str(resource.pk), update_data)

        resource.refresh_from_db()
        assert resource.config["name"] == "Updated Name"
        assert resource.config["metadata"] == {"new": "value"}
        assert resource.config["productId"] == "posthog"
        assert result["name"] == "Updated Name"
        assert result["metadata"] == {"new": "value"}

    def test_delete_resource(self):
        team, resource = self.make_team_with_vercel(self.organization, self.user)
        resource_id = str(resource.pk)
        VercelIntegration.delete_resource(resource_id)
        assert not Integration.objects.filter(pk=resource_id).exists()

    def test_delete_resource_not_found(self):
        with self.assertRaises(NotFound):
            VercelIntegration.delete_resource("999999")

    def test_create_resource_missing_name(self):
        resource_data = {
            "productId": "posthog",
            "metadata": {"key": "value"},
            "billingPlanId": "free",
        }

        with self.assertRaises(exceptions.ValidationError) as context:
            VercelIntegration.create_resource(self.installation_id, resource_data)

        assert "name" in str(context.exception.detail)

    def test_build_secrets(self):
        team = Team.objects.create(organization=self.organization, name="Test Team", api_token="test_api_token")
        secrets = VercelIntegration._build_secrets(team)

        assert len(secrets) == 2
        assert secrets[0]["name"] == "POSTHOG_PROJECT_API_KEY"
        assert secrets[0]["value"] == "test_api_token"
        assert secrets[1]["name"] == "POSTHOG_HOST"
        assert secrets[1]["value"].startswith(("https://", "http://"))

    @parameterized.expand(
        [
            ("exists", lambda self: self.make_team_with_vercel(self.organization, self.user)[0], True),
            (
                "not_found",
                lambda self: Team.objects.create(organization=self.organization, name="No Vercel Team"),
                False,
            ),
        ]
    )
    def test_get_vercel_resource_for_team(self, _, team_factory, should_exist):
        team = team_factory(self)
        result = VercelIntegration._get_vercel_resource_for_team(team)
        assert (result is not None) == should_exist

    @parameterized.expand(
        [
            ("exists", lambda self: self.organization, True),
            ("not_found", lambda self: Organization.objects.create(name="Other Org"), False),
        ]
    )
    def test_get_installation_for_organization(self, _, org_factory, should_exist):
        org = org_factory(self)
        result = VercelIntegration._get_installation_for_organization(org)
        assert (result == self.installation) if should_exist else (result is None)

    @parameterized.expand(
        [
            ("success", {"access_token": "test_token"}, "test_token"),
            ("missing", {}, None),
        ]
    )
    def test_get_access_token(self, _, credentials, expected):
        self.installation.config["credentials"] = credentials
        self.installation.save()
        result = VercelIntegration._get_access_token(self.installation)
        assert result == expected

    @parameterized.expand(
        [
            ("success", False),
            ("failure", True),
        ]
    )
    @patch("ee.vercel.integration.VercelAPIClient")
    @patch("ee.vercel.integration.capture_exception")
    def test_create_vercel_client(self, _, should_fail, mock_capture, mock_client_class):
        token = "bad_token" if should_fail else "good_token"

        if should_fail:
            mock_client_class.side_effect = ValueError("Invalid token")
            assert VercelIntegration._create_vercel_client(token) is None
            mock_capture.assert_called_once()
        else:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            assert VercelIntegration._create_vercel_client(token) == mock_client
            mock_client_class.assert_called_once_with(bearer_token=token)

    @parameterized.expand(
        [
            (
                "flag",
                "make_feature_flag",
                VercelIntegration._convert_feature_flag_to_vercel_item,
                "flag",
                "test_flag",
                "Test Feature Flag",
                False,
                "test-flag",
            ),
            (
                "flag_deleted",
                "make_feature_flag",
                VercelIntegration._convert_feature_flag_to_vercel_item,
                "flag",
                "deleted_flag",
                "Deleted Flag",
                True,
                "deleted-flag",
            ),
            (
                "experiment",
                "make_experiment",
                VercelIntegration._convert_experiment_to_vercel_item,
                "experiment",
                "Test Experiment",
                "A test experiment",
                False,
                "test-experiment",
            ),
            (
                "experiment_archived",
                "make_experiment",
                VercelIntegration._convert_experiment_to_vercel_item,
                "experiment",
                "Archived Experiment",
                "",
                True,
                "archived-experiment",
            ),
        ]
    )
    def test_convert_to_vercel_item(self, _, factory_name, converter, category, name, desc, archived, expected_slug):
        team, _ = self.make_team_with_vercel(self.organization, self.user)
        factory = getattr(self, factory_name)
        item = factory(team, name, desc, archived)
        result = converter(item, created=True)
        self.assert_vercel_item(item, result, category, archived, expected_slug, name, desc)

    @parameterized.expand(
        [
            ("sync_create", "sync", "create_experimentation_items", {"created": True}),
            ("sync_update", "sync", "update_experimentation_item", {"created": False}),
            ("sync_no_client", "sync", None, {"created": True, "has_client": False}),
            ("delete", "delete", "delete_experimentation_item", {}),
        ]
    )
    @patch("ee.vercel.integration.VercelIntegration._setup_vercel_client_for_team")
    def test_vercel_item_operations(self, _, operation_type, client_method, params, mock_setup):
        team, _ = self.make_team_with_vercel(self.organization, self.user)
        has_client = params.get("has_client", True)

        if has_client:
            mock_client = Mock()
            mock_api_result = Mock(success=True)
            getattr(mock_client, client_method).return_value = mock_api_result
            mock_result = Mock(client=mock_client, integration_config_id="config_id", resource_id="resource_id")
            mock_setup.return_value = mock_result
        else:
            mock_setup.return_value = None

        if operation_type == "sync":
            vercel_item = self.make_vercel_item()
            VercelIntegration._sync_item_to_vercel(
                team=team,
                item_type="flag",
                item_pk="123",
                vercel_item=vercel_item,
                created=params.get("created", True),
            )
        else:
            VercelIntegration._delete_item_from_vercel(
                team=team,
                item_type="flag",
                item_id="test_id",
            )

        if has_client:
            getattr(mock_client, client_method).assert_called_once()
        else:
            mock_setup.assert_called_once_with(team)

    @patch("ee.vercel.integration.VercelIntegration._sync_item_to_vercel")
    def test_sync_feature_flag_to_vercel(self, mock_sync):
        team, _ = self.make_team_with_vercel(self.organization, self.user)
        feature_flag = self.make_feature_flag(team, "test_flag", "Test Flag", False)

        VercelIntegration.sync_feature_flag_to_vercel(feature_flag, created=True)
        assert mock_sync.call_count >= 1

    @patch("ee.vercel.integration.VercelIntegration._delete_item_from_vercel")
    def test_delete_feature_flag_from_vercel(self, mock_delete):
        team, _ = self.make_team_with_vercel(self.organization, self.user)
        feature_flag = self.make_feature_flag(team, "test_flag", "Test Flag", False)

        VercelIntegration.delete_feature_flag_from_vercel(feature_flag)

        mock_delete.assert_called_once_with(
            team=team,
            item_type="flag",
            item_id=f"flag_{feature_flag.pk}",
        )

    @patch("ee.vercel.integration.VercelIntegration.delete_feature_flag_from_vercel")
    def test_feature_flag_post_save_signal_deletes_when_marked_deleted(self, mock_delete):
        team, _ = self.make_team_with_vercel(self.organization, self.user)

        feature_flag = FeatureFlag.objects.create(
            team=team,
            key="test_flag",
            name="Test Flag",
            deleted=False,
        )
        mock_delete.reset_mock()

        feature_flag.deleted = True
        feature_flag.save()

        mock_delete.assert_called_once_with(feature_flag)

    @patch("ee.vercel.integration.VercelIntegration.sync_feature_flag_to_vercel")
    def test_feature_flag_post_save_signal_syncs_when_not_deleted(self, mock_sync):
        """Test that post_save signal triggers sync when feature flag is not deleted"""
        team, _ = self.make_team_with_vercel(self.organization, self.user)

        feature_flag = FeatureFlag.objects.create(
            team=team,
            key="test_flag",
            name="Test Flag",
            deleted=False,
        )

        mock_sync.assert_called_with(feature_flag, True)
        mock_sync.reset_mock()

        feature_flag.name = "Updated Test Flag"
        feature_flag.save()

        mock_sync.assert_called_once_with(feature_flag, False)

    @patch("ee.vercel.integration.VercelIntegration.delete_experiment_from_vercel")
    def test_experiment_post_save_signal_deletes_when_marked_deleted(self, mock_delete):
        """Test that post_save signal triggers deletion when experiment is marked as deleted=True"""
        team, _ = self.make_team_with_vercel(self.organization, self.user)

        feature_flag = FeatureFlag.objects.create(team=team, key="exp-flag")

        experiment = Experiment.objects.create(
            team=team,
            name="test_experiment",
            feature_flag=feature_flag,
            deleted=False,
        )
        mock_delete.reset_mock()

        experiment.deleted = True
        experiment.save()

        mock_delete.assert_called_once_with(experiment)

    @patch("ee.vercel.integration.VercelIntegration.sync_experiment_to_vercel")
    def test_experiment_post_save_signal_syncs_when_not_deleted(self, mock_sync):
        """Test that post_save signal triggers sync when experiment is not deleted"""
        team, _ = self.make_team_with_vercel(self.organization, self.user)

        feature_flag = FeatureFlag.objects.create(team=team, key="exp-flag")

        experiment = Experiment.objects.create(
            team=team,
            name="test_experiment",
            feature_flag=feature_flag,
            deleted=False,
        )

        mock_sync.assert_called_with(experiment, True)
        mock_sync.reset_mock()

        experiment.name = "Updated Test Experiment"
        experiment.save()

        mock_sync.assert_called_once_with(experiment, False)
