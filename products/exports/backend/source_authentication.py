from typing import NoReturn

from django.utils import timezone

import structlog

from posthog.api.query import required_scopes_for_query_payload
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.user_permissions import UserPermissions

from products.exports.backend.models.exported_asset import ExportedAsset

logger = structlog.get_logger(__name__)


def get_export_source_authentication(authenticator: object) -> dict[str, str] | None:
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return {
            "source_authentication": ExportedAsset.SourceAuthentication.PERSONAL_API_KEY,
            "source_credential_id": authenticator.personal_api_key.id,
        }
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        return {
            "source_authentication": ExportedAsset.SourceAuthentication.OAUTH_ACCESS_TOKEN,
            "source_credential_id": str(authenticator.access_token.id),
        }
    if isinstance(authenticator, SessionAuthentication):
        return {"source_authentication": ExportedAsset.SourceAuthentication.SESSION}
    return None


def required_scopes_for_export_target(
    *, insight_id: object, dashboard_id: object, export_context: dict | None
) -> list[str]:
    scopes = ["export:write"]
    if insight_id is not None:
        scopes.append("insight:read")
    if dashboard_id is not None:
        scopes.append("dashboard:read")

    context = export_context or {}
    if context.get("session_recording_id"):
        scopes.append("session_recording:read")
    if context.get("heatmap_url"):
        scopes.append("heatmap:read")
    source = context.get("source")
    if source is not None:
        scopes.extend(required_scopes_for_query_payload(source) or ["query:read"])
    return list(dict.fromkeys(scopes))


def required_scopes_for_export(exported_asset: ExportedAsset) -> list[str]:
    return required_scopes_for_export_target(
        insight_id=exported_asset.insight_id,
        dashboard_id=exported_asset.dashboard_id,
        export_context=exported_asset.export_context,
    )


def _credential_has_required_scopes(granted_scopes: list[str], required_scopes: list[str]) -> bool:
    if "*" in granted_scopes:
        return True
    for required_scope in required_scopes:
        valid_scopes = [required_scope]
        if required_scope.endswith(":read"):
            valid_scopes.append(required_scope.replace(":read", ":write"))
        if not any(scope in granted_scopes for scope in valid_scopes):
            return False
    return True


def _raise_invalid_export_authorization(exported_asset: ExportedAsset, reason: str) -> NoReturn:
    logger.error(
        "export.invalid_authentication_source",
        exported_asset_id=exported_asset.id,
        reason=reason,
    )
    raise ValueError("This export could not verify its original authorization. Create a new export and try again.")


def assert_export_authorization(exported_asset: ExportedAsset) -> None:
    source_authentication = exported_asset.source_authentication
    if source_authentication is None:
        return
    created_by = exported_asset.created_by
    if created_by is None or not created_by.is_active:
        _raise_invalid_export_authorization(exported_asset, "missing_export_creator")

    if source_authentication == ExportedAsset.SourceAuthentication.PERSONAL_API_KEY:
        credential = PersonalAPIKey.objects.filter(
            id=exported_asset.source_credential_id,
            user_id=created_by.id,
            user__is_active=True,
        ).first()
        granted_scopes = list(credential.scopes or []) if credential is not None else []
    elif source_authentication == ExportedAsset.SourceAuthentication.OAUTH_ACCESS_TOKEN:
        credential = OAuthAccessToken.objects.filter(
            id=exported_asset.source_credential_id,
            user_id=created_by.id,
            user__is_active=True,
            application__isnull=False,
            expires__gt=timezone.now(),
        ).first()
        granted_scopes = str(credential.scope or "").split() if credential is not None else []
    elif source_authentication == ExportedAsset.SourceAuthentication.SESSION:
        credential = None
        granted_scopes = []
    else:
        _raise_invalid_export_authorization(exported_asset, "unsupported_authentication_source")

    if source_authentication != ExportedAsset.SourceAuthentication.SESSION:
        if credential is None:
            _raise_invalid_export_authorization(exported_asset, "source_credential_invalid")
        if not _credential_has_required_scopes(granted_scopes, required_scopes_for_export(exported_asset)):
            _raise_invalid_export_authorization(exported_asset, "source_credential_lacks_required_scope")
        if credential.scoped_teams and exported_asset.team_id not in credential.scoped_teams:
            _raise_invalid_export_authorization(exported_asset, "source_credential_excludes_project")
        if (
            credential.scoped_organizations
            and str(exported_asset.team.organization_id) not in credential.scoped_organizations
        ):
            _raise_invalid_export_authorization(exported_asset, "source_credential_excludes_organization")

    if UserPermissions(user=created_by, team=exported_asset.team).current_team.effective_membership_level is None:
        _raise_invalid_export_authorization(exported_asset, "creator_lacks_project_access")
