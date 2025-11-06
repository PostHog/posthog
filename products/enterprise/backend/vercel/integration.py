import copy
import hmac
import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Union
from urllib.parse import quote, urlencode

from django.conf import settings
from django.contrib.auth import login
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

import structlog
from rest_framework import exceptions

from posthog.event_usage import report_user_signed_up
from posthog.exceptions_capture import capture_exception
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.product_intent import ProductIntent
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import absolute_uri

from products.enterprise.backend.api.authentication import VercelAuthentication
from products.enterprise.backend.api.vercel.types import VercelClaims, VercelUserClaims
from products.enterprise.backend.vercel.client import SSOTokenResponse, VercelAPIClient

logger = structlog.get_logger(__name__)

VercelItemType = Literal["flag", "experiment"]


class VercelSSOError(Exception):
    pass


class RequiresExistingUserLogin(Exception):
    def __init__(self, email: str, vercel_user_id: str, installation_id: str):
        self.email = email
        self.vercel_user_id = vercel_user_id
        self.installation_id = installation_id
        super().__init__(f"User {email} must login first")


@dataclass
class SSOParams:
    mode: str
    code: str
    state: str
    product_id: str | None = None
    resource_id: str | None = None
    project_id: str | None = None
    experimentation_item_id: str | None = None
    path: str | None = None
    url: str | None = None

    def to_dict_no_nulls(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ResourceConfig:
    productId: str
    name: str
    metadata: dict[str, Any]
    billingPlanId: str
    externalId: str | None = None
    protocolSettings: dict[str, Any] | None = None


@dataclass
class InstallationCredentials:
    access_token: str
    token_type: str


@dataclass
class InstallationContact:
    email: str
    name: str | None = None


@dataclass
class InstallationAccount:
    url: str
    contact: InstallationContact
    name: str | None = None


@dataclass
class InstallationConfig:
    scopes: list[str]
    acceptedPolicies: dict[str, Any]
    credentials: InstallationCredentials
    account: InstallationAccount


@dataclass
class VercelSetupResult:
    client: VercelAPIClient
    integration_config_id: str
    resource_id: str


@dataclass
class SSOExperimentationConfig:
    model: Union[type[FeatureFlag], type[Experiment]]
    url_template: str


class VercelIntegration:
    SSO_PATH_REDIRECT_MAP = {
        "billing": "/organization/billing/overview",
        "usage": "/organization/billing/usage",
        "support": "/#panel=support",
    }
    SSO_DEFAULT_REDIRECT = "/"

    # If this grows too big, or we start doing SSO in multiple integrations,
    # this could be handled in the frontend instead.
    SSO_EXPERIMENTATION_CONFIG: dict[str, SSOExperimentationConfig] = {
        "flag": SSOExperimentationConfig(
            model=FeatureFlag,
            url_template="/project/{team_id}/feature_flags/{item_pk}",
        ),
        "experiment": SSOExperimentationConfig(
            model=Experiment,
            url_template="/project/{team_id}/experiments/{item_pk}",
        ),
    }

    @staticmethod
    def _get_installation(installation_id: str) -> OrganizationIntegration:
        try:
            return OrganizationIntegration.objects.get(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=installation_id
            )
        except OrganizationIntegration.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

    @staticmethod
    def _get_resource(resource_id: str) -> Integration:
        try:
            return Integration.objects.get(pk=resource_id, kind=Integration.IntegrationKind.VERCEL)
        except Integration.DoesNotExist:
            raise exceptions.NotFound("Resource not found")

    @staticmethod
    def _validate_resource_belongs_to_installation(
        resource: Integration, installation: OrganizationIntegration
    ) -> None:
        if not resource.team.organization.organizationintegration_set.filter(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL, integration_id=installation.integration_id
        ).exists():
            raise exceptions.ValidationError({"resource": "Resource does not belong to this installation."})

    @staticmethod
    def _get_resource_with_installation(resource_id: str) -> tuple[Integration, OrganizationIntegration]:
        resource = VercelIntegration._get_resource(resource_id)
        org_integration = resource.team.organization.organizationintegration_set.get(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL
        )
        if not org_integration.integration_id:
            raise exceptions.NotFound("Installation not found")
        installation = VercelIntegration._get_installation(org_integration.integration_id)
        return resource, installation

    @staticmethod
    def get_vercel_plans() -> list[dict[str, Any]]:
        # TODO: Retrieve through billing service instead.
        return [
            {
                "id": "free",
                "type": "subscription",
                "name": "Free",
                "description": "No credit card required",
                "scope": "installation",
                "paymentMethodRequired": False,
                "details": [
                    {"label": "Data retention", "value": "1 year"},
                    {"label": "Projects", "value": "1"},
                    {"label": "Team members", "value": "Unlimited"},
                    {"label": "API Access", "value": "✓"},
                    {"label": "No limits on tracked users", "value": "✓"},
                    {"label": "Community support", "value": "Support via community forum"},
                ],
                "highlightedDetails": [
                    {"label": "Feature Flags", "value": "1 million free requests"},
                    {"label": "Experiments", "value": "1 million free requests"},
                ],
            },
            {
                "id": "pay_as_you_go",
                "type": "subscription",
                "name": "Pay-as-you-go",
                "description": "Usage-based pricing after free tier",
                "scope": "installation",
                "paymentMethodRequired": True,
                "details": [
                    {"label": "Data retention", "value": "7 years"},
                    {"label": "Projects", "value": "6"},
                    {"label": "Team members", "value": "Unlimited"},
                    {"label": "API Access", "value": "✓"},
                    {"label": "No limits on tracked users", "value": "✓"},
                    {"label": "Standard support", "value": "Support via email, Slack-based over $2k/mo"},
                ],
                "highlightedDetails": [
                    {"label": "Feature flags", "value": "1 million requests for free, then from $0.0001/request"},
                    {"label": "Experiments", "value": "Billed with feature flags"},
                ],
            },
        ]

    @staticmethod
    def upsert_installation(installation_id: str, payload: dict[str, Any], user_claims: VercelUserClaims) -> None:
        account_data = payload.get("account", {})
        contact_data = account_data.get("contact", {})
        credentials_data = payload.get("credentials", {})

        vercel_user_id = user_claims.user_id

        contact = InstallationContact(email=contact_data["email"], name=contact_data.get("name"))

        credentials = InstallationCredentials(
            access_token=credentials_data["access_token"], token_type=credentials_data["token_type"]
        )

        account = InstallationAccount(url=account_data["url"], contact=contact, name=account_data.get("name"))

        config = InstallationConfig(
            scopes=payload["scopes"],
            acceptedPolicies=payload["acceptedPolicies"],
            credentials=credentials,
            account=account,
        )

        logger.info(
            "Starting Vercel installation upsert process", installation_id=installation_id, integration="vercel"
        )

        # Check if there's already an OrganizationIntegration for this installation_id
        # If there is, we don't need to do update anything besides OrganizationIntegration's config.
        organization_integration_exists = OrganizationIntegration.objects.filter(
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=installation_id,
        ).exists()

        if organization_integration_exists:
            OrganizationIntegration.objects.filter(
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                integration_id=installation_id,
            ).update(config=asdict(config))
            logger.info("Vercel installation updated", installation_id=installation_id, integration="vercel")
            return

        with transaction.atomic():
            # Through Vercel we can only create new organizations, not use existing ones.
            # Note: We won't create a team here, that's done during Vercel resource creation.
            organization = Organization.objects.create(
                name=config.account.name or f"Vercel Installation {installation_id}"
            )

            # Check if user already exists - if so, don't create mapping yet (wait for SSO) where user proves
            # they have access to the account associated with the email they're using.
            existing_user = User.objects.filter(email=config.account.contact.email, is_active=True).first()

            if existing_user:
                # Existing user - create organization and integration but no user mapping or org membership yet
                # They'll need to login first before connecting via SSO and being added to the org
                # Store the intended membership level for when they complete SSO
                user = existing_user
                user_created = False
            else:
                user, user_created = VercelIntegration._find_or_create_user_by_email(
                    email=config.account.contact.email,
                    name=config.account.contact.name,
                    organization=organization,
                    level=OrganizationMembership.Level.OWNER,  # User installing gets owner level
                )

            try:
                org_integration, _ = OrganizationIntegration.objects.update_or_create(
                    organization=organization,
                    kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                    integration_id=installation_id,
                    defaults={
                        "config": asdict(config),
                        "created_by": user,
                    },
                )

                # Only create user mapping for new users, existing users get mapped during SSO
                if user_created:
                    VercelIntegration._set_user_mapping(org_integration, vercel_user_id, user.pk)

                logger.info("Created new Vercel installation", installation_id=installation_id, integration="vercel")
            except IntegrityError as e:
                capture_exception(e)
                logger.exception(
                    "Failed to create Vercel installation", installation_id=installation_id, integration="vercel"
                )
                raise exceptions.ValidationError(
                    {"validation_error": "Something went wrong."},
                    code="unique",
                )

        if user_created:
            report_user_signed_up(
                user,
                is_instance_first_user=False,
                is_organization_first_user=True,
                backend_processor="VercelIntegration",
                user_analytics_metadata=user.get_analytics_metadata(),
                org_analytics_metadata=organization.get_analytics_metadata(),
                social_provider="vercel",
                referral_source="vercel",
            )

        logger.info(
            "Successfully created Vercel installation",
            installation_id=installation_id,
            organization_id=organization.id,
            integration="vercel",
        )

    @staticmethod
    def get_installation_billing_plan(installation_id: str) -> dict[str, Any]:
        VercelIntegration._get_installation(installation_id)
        billing_plans = VercelIntegration.get_vercel_plans()

        # Always return free plan for now - will be replaced with billing service
        current_plan = next(plan for plan in billing_plans if plan["id"] == "free")

        return {
            "billingplan": current_plan,
        }

    @staticmethod
    def update_installation(installation_id: str, billing_plan_id: str) -> None:
        logger.info("Starting Vercel installation update", installation_id=installation_id, integration="vercel")

        # TODO: Implement billing plan update logic here, awaiting billing service implementation.

        logger.info("Successfully updated Vercel installation", installation_id=installation_id, integration="vercel")

    @staticmethod
    def delete_installation(installation_id: str) -> dict[str, Any]:
        logger.info("Starting Vercel installation deletion", installation_id=installation_id, integration="vercel")
        installation = VercelIntegration._get_installation(installation_id)
        installation.delete()
        is_dev = settings.DEBUG
        logger.info(
            "Successfully deleted Vercel installation",
            installation_id=installation_id,
            finalized=is_dev,
            integration="vercel",
        )
        return {"finalized": is_dev}  # Immediately finalize in dev mode for testing purposes

    @staticmethod
    def get_product_plans(product_slug: str) -> dict[str, Any]:
        if product_slug != "posthog":
            raise exceptions.NotFound("Product not found")

        return {"plans": VercelIntegration.get_vercel_plans()}

    @staticmethod
    def create_resource(installation_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "Starting Vercel resource creation",
            installation_id=installation_id,
            resource_name=resource_data.get("name"),
            integration="vercel",
        )

        if not resource_data.get("name"):
            raise exceptions.ValidationError({"name": "Resource name is required."})

        config = ResourceConfig(**resource_data)

        installation = VercelIntegration._get_installation(installation_id)
        organization: Organization = installation.organization

        team = Team.objects.create_with_data(
            initiating_user=installation.created_by or None,
            organization=organization,
            name=config.name,
            has_completed_onboarding_for={
                "product_analytics": True
            },  # Mark one product as onboarded to show quick start sidebar
        )

        if installation.created_by:
            ProductIntent.register(
                team=team,
                product_type="feature_flags",
                context="vercel integration",
                user=installation.created_by,
            )

            ProductIntent.register(
                team=team,
                product_type="experiments",
                context="vercel integration",
                user=installation.created_by,
            )

        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config=asdict(config),
            created_by=installation.created_by,
        )

        logger.info(
            "Successfully created Vercel resource",
            installation_id=installation_id,
            resource_id=resource.pk,
            team_id=team.pk,
            integration="vercel",
        )

        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def get_resource(resource_id: str) -> dict[str, Any]:
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def update_resource(resource_id: str, resource_data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Starting Vercel resource update", resource_id=resource_id, integration="vercel")
        resource, installation = VercelIntegration._get_resource_with_installation(resource_id)

        updated_config = copy.deepcopy(resource.config)
        updated_config.update(resource_data)

        validated_config = ResourceConfig(**updated_config)
        resource.config = asdict(validated_config)
        resource.save(update_fields=["config"])

        logger.info("Successfully updated Vercel resource", resource_id=resource_id, integration="vercel")
        return VercelIntegration._build_resource_response(resource, installation)

    @staticmethod
    def delete_resource(resource_id: str) -> None:
        logger.info("Starting Vercel resource deletion", resource_id=resource_id, integration="vercel")
        resource, _ = VercelIntegration._get_resource_with_installation(resource_id)
        resource.delete()
        logger.info("Successfully deleted Vercel resource", resource_id=resource_id, integration="vercel")

    @staticmethod
    def _build_resource_response(resource: Integration, installation: OrganizationIntegration) -> dict[str, Any]:
        billing_plans = VercelIntegration.get_vercel_plans()
        current_plan_id = installation.config.get("billing_plan_id", "free")  # TODO: Replace with billing service
        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)

        return {
            "id": str(resource.pk),
            "productId": resource.config.get("productId", ""),
            "name": resource.config.get("name", resource.team.name),
            "metadata": resource.config.get("metadata", {}),
            "status": "ready",
            "secrets": VercelIntegration._build_secrets(resource.team),
            "billingPlan": current_plan,
        }

    @staticmethod
    def _build_secrets(team: Team) -> list[dict[str, str]]:
        return [
            {
                "name": "POSTHOG_PROJECT_API_KEY",
                "value": team.api_token,
            },
            {
                "name": "POSTHOG_HOST",
                "value": absolute_uri(),
            },
        ]

    @staticmethod
    def _get_vercel_resource_for_team(team: Team) -> Integration | None:
        try:
            return Integration.objects.get(team=team, kind=Integration.IntegrationKind.VERCEL)
        except Integration.DoesNotExist:
            return None

    @staticmethod
    def _get_installation_for_organization(organization: Organization) -> OrganizationIntegration | None:
        try:
            return OrganizationIntegration.objects.get(
                organization=organization, kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL
            )
        except OrganizationIntegration.DoesNotExist:
            return None

    @staticmethod
    def _get_access_token(installation: OrganizationIntegration) -> str | None:
        access_token = installation.config.get("credentials", {}).get("access_token")
        if not access_token:
            logger.exception(
                "Missing access token for Vercel installation",
                installation_id=installation.integration_id,
                integration="vercel",
            )
        return access_token

    @staticmethod
    def _create_vercel_client(access_token: str) -> VercelAPIClient | None:
        try:
            return VercelAPIClient(bearer_token=access_token)
        except ValueError as e:
            logger.exception("Failed to create Vercel API client", integration="vercel")
            capture_exception(e)
            return None

    @staticmethod
    def _setup_vercel_client_for_team(team: Team) -> VercelSetupResult | None:
        resource = VercelIntegration._get_vercel_resource_for_team(team)
        if not resource:
            logger.debug("Vercel resource not found for team", team_id=team.id, integration="vercel")
            return None

        installation = VercelIntegration._get_installation_for_organization(team.organization)
        if not installation:
            logger.debug(
                "Vercel installation not found for organization",
                team_id=team.pk,
                organization_id=team.organization.pk,
                integration="vercel",
            )
            return None

        access_token = VercelIntegration._get_access_token(installation)
        if not access_token:
            logger.exception(
                "Failed to get access token for Vercel installation",
                installation_id=installation.integration_id,
                team_id=team.pk,
                integration="vercel",
            )
            return None

        client = VercelIntegration._create_vercel_client(access_token)
        if not client:
            logger.exception(
                "Failed to create Vercel API client",
                installation_id=installation.integration_id,
                team_id=team.pk,
                integration="vercel",
            )
            return None

        integration_config_id = installation.integration_id
        if not integration_config_id:
            logger.exception(
                "Missing integration_id in installation",
                installation_id=installation.pk,
                team_id=team.pk,
                integration="vercel",
            )
            return None

        resource_id = str(resource.pk)

        logger.debug(
            "Successfully set up Vercel client",
            team_id=team.pk,
            integration_config_id=integration_config_id,
            resource_id=resource_id,
            integration="vercel",
        )
        return VercelSetupResult(
            client=client,
            integration_config_id=integration_config_id,
            resource_id=resource_id,
        )

    @staticmethod
    def _get_vercel_item_id(item_type: VercelItemType, item_id: str | int) -> str:
        return f"{item_type}_{item_id}"

    @staticmethod
    def _sync_item_to_vercel(
        team: Team,
        item_type: VercelItemType,
        item_pk: str | int,
        vercel_item: dict,
        created: bool,
    ) -> None:
        setup_result = VercelIntegration._setup_vercel_client_for_team(team)
        if not setup_result:
            return

        item_id = VercelIntegration._get_vercel_item_id(item_type, item_pk)

        if created:
            result = setup_result.client.create_experimentation_items(
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                items=[vercel_item],
            )
            if result.success:
                logger.info(
                    f"{item_type} created in Vercel",
                    item_id=item_id,
                    integration_config_id=setup_result.integration_config_id,
                    resource_id=setup_result.resource_id,
                    integration="vercel",
                )
            else:
                logger.exception(
                    f"Failed to create {item_type} in Vercel",
                    item_id=item_id,
                    error=result.error,
                    integration="vercel",
                )
        else:
            result = setup_result.client.update_experimentation_item(
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                item_id=item_id,
                data=vercel_item,
            )
            if result.success:
                logger.info(
                    f"{item_type} updated in Vercel",
                    item_id=item_id,
                    integration_config_id=setup_result.integration_config_id,
                    resource_id=setup_result.resource_id,
                    integration="vercel",
                )
            else:
                logger.exception(
                    f"Failed to update {item_type} in Vercel",
                    item_id=item_id,
                    error=result.error,
                    integration="vercel",
                )

    @staticmethod
    def sync_feature_flag_to_vercel(feature_flag: FeatureFlag, created: bool) -> None:
        vercel_item = VercelIntegration._convert_feature_flag_to_vercel_item(feature_flag, created)
        VercelIntegration._sync_item_to_vercel(
            team=feature_flag.team,
            item_type="flag",
            item_pk=feature_flag.pk,
            vercel_item=vercel_item,
            created=created,
        )

    @staticmethod
    def _delete_item_from_vercel(team: Team, item_type: VercelItemType, item_id: str) -> None:
        setup_result = VercelIntegration._setup_vercel_client_for_team(team)
        if not setup_result:
            return

        logger.debug(f"Starting Vercel {item_type} deletion", item_id=item_id, integration="vercel")
        result = setup_result.client.delete_experimentation_item(
            integration_config_id=setup_result.integration_config_id,
            resource_id=setup_result.resource_id,
            item_id=item_id,
        )
        if result.success:
            logger.info(
                f"{item_type} deleted from Vercel",
                item_id=item_id,
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                integration="vercel",
            )
        else:
            logger.exception(
                f"Failed to delete {item_type} from Vercel",
                item_id=item_id,
                integration_config_id=setup_result.integration_config_id,
                resource_id=setup_result.resource_id,
                error=result.error,
                integration="vercel",
            )

    @staticmethod
    def delete_feature_flag_from_vercel(feature_flag: FeatureFlag) -> None:
        VercelIntegration._delete_item_from_vercel(
            team=feature_flag.team,
            item_type="flag",
            item_id=VercelIntegration._get_vercel_item_id("flag", feature_flag.pk),
        )

    @staticmethod
    def sync_experiment_to_vercel(experiment: Experiment, created: bool) -> None:
        vercel_item = VercelIntegration._convert_experiment_to_vercel_item(experiment, created)
        VercelIntegration._sync_item_to_vercel(
            team=experiment.team,
            item_type="experiment",
            item_pk=experiment.pk,
            vercel_item=vercel_item,
            created=created,
        )

    @staticmethod
    def delete_experiment_from_vercel(experiment: Experiment) -> None:
        VercelIntegration._delete_item_from_vercel(
            team=experiment.team,
            item_type="experiment",
            item_id=VercelIntegration._get_vercel_item_id("experiment", experiment.pk),
        )

    @staticmethod
    def _convert_feature_flag_to_vercel_item(feature_flag: FeatureFlag, created: bool) -> dict:
        return {
            **({"id": VercelIntegration._get_vercel_item_id("flag", feature_flag.pk)} if created else {}),
            "slug": feature_flag.key,
            "origin": absolute_uri(f"/project/{feature_flag.team.id}/feature_flags/{feature_flag.pk}"),
            "category": "flag",
            "name": feature_flag.key,
            "description": feature_flag.name,
            "isArchived": feature_flag.deleted,
            "createdAt": int(feature_flag.created_at.timestamp() * 1000),
            "updatedAt": int(timezone.now().timestamp() * 1000),
        }

    @staticmethod
    def _convert_experiment_to_vercel_item(experiment: Experiment, created: bool) -> dict:
        return {
            **({"id": VercelIntegration._get_vercel_item_id("experiment", experiment.pk)} if created else {}),
            "slug": slugify(experiment.name) or f"experiment-{experiment.pk}",
            "origin": absolute_uri(f"/project/{experiment.team.id}/experiments/{experiment.pk}"),
            "category": "experiment",
            "name": experiment.name,
            "description": experiment.description or "",
            "isArchived": experiment.archived or experiment.deleted,
            "createdAt": int(experiment.created_at.timestamp() * 1000),
            "updatedAt": int(experiment.updated_at.timestamp() * 1000),
        }

    @staticmethod
    def _validate_client_credentials() -> tuple[str, str]:
        if not getattr(settings, "VERCEL_CLIENT_INTEGRATION_ID", None):
            raise exceptions.NotFound("Vercel integration not configured: missing VERCEL_CLIENT_INTEGRATION_ID")
        if not getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", None):
            raise exceptions.NotFound("Vercel integration not configured: missing VERCEL_CLIENT_INTEGRATION_SECRET")
        return settings.VERCEL_CLIENT_INTEGRATION_ID, settings.VERCEL_CLIENT_INTEGRATION_SECRET

    @staticmethod
    def _get_sso_claims_from_code(code: str, state: str | None) -> VercelClaims:
        client_id, client_secret = VercelIntegration._validate_client_credentials()

        # Exchange code + state for token
        token_response = VercelIntegration._exchange_sso_token(code, client_id, client_secret, state)

        if not token_response.id_token:
            raise exceptions.AuthenticationFailed("Vercel SSO response missing id_token")

        # Then exchange token for claim
        claims = VercelAuthentication()._validate_jwt_token(token_response.id_token, "user")

        if not isinstance(claims, VercelUserClaims):
            raise NotImplementedError("SSO is only supported for user claims, not system claims")

        # Cache claims for potential existing user login flow (needed because the code can only be exchanged once)
        VercelIntegration._set_cached_claims(code, claims, timeout=300)  # 5 minutes

        return claims

    @staticmethod
    def _authenticate_and_login_user(request, claims: VercelUserClaims, resource_id: str | None) -> User:
        user = VercelIntegration._find_sso_user(claims)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        if resource_id:
            VercelIntegration.set_active_project(user, resource_id)
        return user

    @staticmethod
    def complete_sso_for_logged_in_user(request, params: SSOParams) -> str:
        if not request.user.is_authenticated:
            raise exceptions.AuthenticationFailed("User must be logged in")

        try:
            claims = VercelIntegration._get_cached_claims(params.code)

            if claims is None:
                raise exceptions.AuthenticationFailed("SSO claims not found in cache")

            if not isinstance(claims, VercelUserClaims):
                raise NotImplementedError("SSO is only supported for user claims, not system claims")

            if not claims.user_email or request.user.email.lower() != claims.user_email.lower():
                raise exceptions.PermissionDenied("Email verification failed for SSO")

            with transaction.atomic():
                installation = OrganizationIntegration.objects.select_for_update().get(
                    kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                    integration_id=claims.installation_id,
                )

                intended_level = VercelIntegration._determine_membership_level(request.user.email, installation)
                created = VercelIntegration._ensure_user_membership(
                    request.user, installation.organization, intended_level
                )

                VercelIntegration._set_user_mapping(installation, claims.user_id, request.user.pk)

            request.user.current_organization = installation.organization
            request.user.save(update_fields=["current_organization"])

            # Set active project if provided, otherwise set the user's current organization
            if params.resource_id:
                VercelIntegration.set_active_project(request.user, params.resource_id)

            redirect_url = VercelIntegration.determine_sso_redirect(
                path=params.path,
                url=params.url,
                experimentation_item_id=params.experimentation_item_id,
                user=request.user,
            )

            logger.info(
                "Vercel SSO completed for existing user",
                resource_id=params.resource_id,
                installation_id=claims.installation_id,
                membership_level=intended_level.label,
                membership_created=created,
                method="existing_user_flow",
                integration="vercel",
            )
            return redirect_url
        except Exception as e:
            logger.exception("Vercel SSO completion failed", error=str(e), integration="vercel")
            raise exceptions.AuthenticationFailed("SSO completion failed")

    @staticmethod
    def _determine_membership_level(
        user_email: str, installation: OrganizationIntegration
    ) -> OrganizationMembership.Level:
        installer_email = installation.config.get("account", {}).get("contact", {}).get("email")
        if installer_email and installer_email.lower() == user_email.lower():
            return OrganizationMembership.Level.OWNER
        return OrganizationMembership.Level.MEMBER

    @staticmethod
    def _ensure_user_membership(
        user: User, organization: Organization, level: OrganizationMembership.Level
    ) -> tuple[OrganizationMembership, bool]:
        membership, created = OrganizationMembership.objects.get_or_create(
            user=user, organization=organization, defaults={"level": level}
        )

        if not created and membership.level < level:
            membership.level = level
            membership.save(update_fields=["level"])

        return membership, created

    @staticmethod
    def _get_cache_key(code: str) -> str:
        # Hash to prevent guessability (bit paranoid but better safe than sorry)
        cache_salt = hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()
        return f"vercel_sso_claims:{cache_salt}"

    @staticmethod
    def _get_cached_claims(code: str) -> VercelUserClaims | None:
        claims_key = VercelIntegration._get_cache_key(code)
        claims = cache.get(claims_key)

        if claims:
            cache.delete(claims_key)  # These intended as single-use codes

        return claims

    @staticmethod
    def _set_cached_claims(code: str, claims: VercelUserClaims, timeout: int = 300) -> None:
        claims_key = VercelIntegration._get_cache_key(code)
        cache.set(claims_key, claims, timeout=timeout)

    @staticmethod
    def authenticate_sso(request, params: SSOParams) -> str:
        try:
            claims = VercelIntegration._get_sso_claims_from_code(params.code, params.state)
            if not isinstance(claims, VercelUserClaims):
                raise NotImplementedError("SSO is only supported for user claims, not system claims")

            user = VercelIntegration._authenticate_and_login_user(request, claims, params.resource_id)

            redirect_url = VercelIntegration.determine_sso_redirect(
                path=params.path,
                url=params.url,
                experimentation_item_id=params.experimentation_item_id,
                user=user,
            )

            logger.info(
                "Vercel SSO login successful",
                resource_id=params.resource_id,
                method="new_user_flow",
                integration="vercel",
            )
            return redirect_url
        except RequiresExistingUserLogin as e:
            continuation_url = f"/login/vercel/continue?{urlencode(params.to_dict_no_nulls())}"
            login_url = f"/login?next={quote(continuation_url)}"

            logger.info(
                "Vercel SSO requires existing user login",
                installation_id=e.installation_id,
                method="login_redirect_flow",
                integration="vercel",
            )
            return login_url
        except Exception as e:
            logger.exception("Vercel SSO authentication failed", error=str(e), integration="vercel")
            raise exceptions.AuthenticationFailed("Authentication failed")

    @staticmethod
    def _exchange_sso_token(code: str, client_id: str, client_secret: str, state: str | None) -> SSOTokenResponse:
        client = VercelAPIClient(bearer_token=None)
        response = client.sso_token_exchange(code=code, client_id=client_id, client_secret=client_secret, state=state)
        if not response or response.error:
            error_msg = response.error if response else "Token exchange failed"
            raise exceptions.AuthenticationFailed(f"Vercel token exchange failed: {error_msg}")
        return response

    @staticmethod
    def _get_user_mapping(installation: OrganizationIntegration, vercel_user_id: str) -> int | None:
        user_mappings = installation.config.get("user_mappings", {})
        return user_mappings.get(vercel_user_id)

    @staticmethod
    def _set_user_mapping(installation: OrganizationIntegration, vercel_user_id: str, user_pk: int) -> None:
        """
        We can't utilize user emails provided by Vercel for user mappings. Instead of that Vercel gives us a user id,
        which is based on the Vercel account ID, the integration ID, and the installation ID.
        We can store this on the OrganizationIntegration config since it's bound to an installation.
        """
        if "user_mappings" not in installation.config:
            installation.config["user_mappings"] = {}
        installation.config["user_mappings"][vercel_user_id] = user_pk
        installation.save(update_fields=["config"])

    @staticmethod
    def _find_or_create_user_by_email(
        email: str, name: str | None, organization: Organization, level: OrganizationMembership.Level
    ) -> tuple[User, bool]:
        user = User.objects.filter(email=email, is_active=True).first()
        created = False

        if not user:
            first_name = ""
            if name:
                first_name = name.split()[0] if name.split() else name
            elif email:
                first_name = email.split("@")[0]

            user = User.objects.create_user(
                email=email,
                password=None,
                first_name=first_name,
                is_staff=False,
                is_email_verified=False,
            )
            created = True

        VercelIntegration._ensure_user_membership(user, organization, level)

        return user, created

    @staticmethod
    def _find_sso_user(claims: VercelUserClaims) -> User:
        if not claims.user_email:
            raise ValueError("Email is required for user creation")

        installation = VercelIntegration._get_installation(claims.installation_id)

        # Try to find already mapped user
        user_pk = VercelIntegration._get_user_mapping(installation, claims.user_id)
        if user_pk:
            user = User.objects.filter(pk=user_pk, is_active=True).first()
            if user:
                # Validate that the user still has access to the organization associated with the installation
                if not user.organization_memberships.filter(
                    organization=installation.organization, level__gte=OrganizationMembership.Level.MEMBER
                ).exists():
                    # User no longer has access to this organization, remove stale mapping
                    user_mappings = installation.config.get("user_mappings", {})
                    if claims.user_id in user_mappings:
                        del user_mappings[claims.user_id]
                        installation.save(update_fields=["config"])
                    raise exceptions.PermissionDenied("User no longer has access to this organization")
                return user
            # User was deleted, remove stale mapping
            user_mappings = installation.config.get("user_mappings", {})
            if claims.user_id in user_mappings:
                del user_mappings[claims.user_id]
                installation.save(update_fields=["config"])

        existing_user = User.objects.filter(email=claims.user_email, is_active=True).first()
        if existing_user:
            raise RequiresExistingUserLogin(
                email=claims.user_email, vercel_user_id=claims.user_id, installation_id=claims.installation_id
            )

        intended_level = VercelIntegration._determine_membership_level(claims.user_email, installation)

        user, _ = VercelIntegration._find_or_create_user_by_email(
            email=claims.user_email,
            name=claims.user_name,
            organization=installation.organization,
            level=intended_level,
        )

        VercelIntegration._set_user_mapping(installation, claims.user_id, user.pk)
        return user

    @staticmethod
    def determine_sso_redirect(
        path: str | None, url: str | None, experimentation_item_id: str | None, user: User
    ) -> str:
        if url:
            return url

        if experimentation_item_id:
            if item_url := VercelIntegration._get_sso_experimentation_url(experimentation_item_id, user):
                return item_url
            logger.warning(
                "Invalid experimentation item",
                experimentation_item_id=experimentation_item_id,
                url=url,
                integration="vercel",
            )

        if path in VercelIntegration.SSO_PATH_REDIRECT_MAP:
            return VercelIntegration.SSO_PATH_REDIRECT_MAP[path]

        return VercelIntegration.SSO_DEFAULT_REDIRECT

    @staticmethod
    def _get_sso_experimentation_url(item_id: str, user: User) -> str | None:
        if not item_id:
            return None

        item_type, item_pk = VercelIntegration._parse_sso_item_id(item_id)
        if not item_type or not item_pk:
            return None

        config = VercelIntegration.SSO_EXPERIMENTATION_CONFIG.get(item_type)
        if not config:
            return None

        model_class = config.model
        item = model_class.objects.filter(pk=item_pk).first()
        if not item:
            return None

        # Sanity check to ensure the user has access to the item's team
        if not user.teams.filter(pk=item.team.pk).exists():
            return None

        return config.url_template.format(team_id=item.team.id, item_pk=item.pk)

    @staticmethod
    def _parse_sso_item_id(item_id: str) -> tuple[str | None, int | None]:
        for item_type in VercelIntegration.SSO_EXPERIMENTATION_CONFIG:
            prefix = f"{item_type}_"
            if not item_id.startswith(prefix):
                continue

            id_str = item_id[len(prefix) :]
            if id_str.isdigit():
                return item_type, int(id_str)

        return None, None

    @staticmethod
    def set_active_project(user: User, resource_id: str):
        resource = Integration.objects.filter(pk=resource_id, kind=Integration.IntegrationKind.VERCEL).first()
        if not resource:
            raise exceptions.NotFound(f"Vercel resource not found: {resource_id}")

        team = resource.team
        if not team:
            raise exceptions.ValidationError(f"Resource has no associated team: {resource_id}")

        if not user.teams.filter(pk=team.pk).exists():
            raise exceptions.PermissionDenied(f"User not member of team for resource: {resource_id}")

        user.current_team = team
        user.save()
        return resource, user, team


def _safe_vercel_sync(operation_name: str, item_id: str | int, team: Team, sync_func: Callable[[], None]) -> None:
    """
    Safety wrapper for Vercel sync operations triggered by Django signals.

    Django signals run synchronously within the same database transaction as the save/delete operation.
    Without this wrapper, any network failure or API error from Vercel would cause the entire database operation to fail,
    blocking users from saving or deleting their feature flags and experiments.

    Operations are silently skipped if Vercel integration is not configured and
    exceptions are caught and logged rather than bubbling up to the caller.
    """
    if not VercelIntegration._get_vercel_resource_for_team(team):
        return

    try:
        sync_func()
    except Exception as e:
        logger.exception(
            f"Failed to {operation_name}",
            item_id=item_id,
            integration="vercel",
        )
        capture_exception(e)


@receiver(post_save, sender=FeatureFlag)
def sync_feature_flag_experimentation_item(sender, instance: FeatureFlag, created, **kwargs):
    if instance.deleted:
        _safe_vercel_sync(
            "delete feature flag from Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.delete_feature_flag_from_vercel(instance),
        )
    else:
        _safe_vercel_sync(
            "sync feature flag to Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.sync_feature_flag_to_vercel(instance, created),
        )


@receiver(post_delete, sender=FeatureFlag)
def delete_resource_experimentation_item(sender, instance: FeatureFlag, **kwargs):
    _safe_vercel_sync(
        "delete feature flag from Vercel",
        instance.pk,
        instance.team,
        lambda: VercelIntegration.delete_feature_flag_from_vercel(instance),
    )


@receiver(post_save, sender=Experiment)
def sync_experiment_experimentation_item(sender, instance: Experiment, created, **kwargs):
    if instance.deleted:
        _safe_vercel_sync(
            "delete experiment from Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.delete_experiment_from_vercel(instance),
        )
    else:
        _safe_vercel_sync(
            "sync experiment to Vercel",
            instance.pk,
            instance.team,
            lambda: VercelIntegration.sync_experiment_to_vercel(instance, created),
        )


@receiver(post_delete, sender=Experiment)
def delete_experiment_experimentation_item(sender, instance: Experiment, **kwargs):
    _safe_vercel_sync(
        "delete experiment from Vercel",
        instance.pk,
        instance.team,
        lambda: VercelIntegration.delete_experiment_from_vercel(instance),
    )
