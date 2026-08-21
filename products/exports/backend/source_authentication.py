from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication

from products.exports.backend.models.exported_asset import ExportedAsset


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
