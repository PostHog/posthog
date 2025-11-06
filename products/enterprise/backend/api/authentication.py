import re
from typing import Any, Literal, Union, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http.response import HttpResponse
from django.urls.base import reverse

import jwt
import structlog
import posthoganalytics
from jwt.algorithms import RSAAlgorithm
from rest_framework import authentication
from rest_framework.decorators import api_view
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.request import Request
from social_core.backends.google import GoogleOAuth2
from social_core.backends.saml import (
    OID_COMMON_NAME,
    OID_GIVEN_NAME,
    OID_MAIL,
    OID_SURNAME,
    OID_USERID,
    SAMLAuth,
    SAMLIdentityProvider,
)
from social_core.exceptions import AuthFailed, AuthMissingParameter
from social_django.models import UserSocialAuth
from social_django.utils import load_backend, load_strategy

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain

from products.enterprise.backend.api.vercel.types import VercelClaims, VercelSystemClaims, VercelUser, VercelUserClaims
from products.enterprise.backend.api.vercel.utils import get_vercel_jwks

from ee import settings


@api_view(["GET"])
def saml_metadata_view(request, *args, **kwargs):
    if (
        not request.user.organization_memberships.get(organization=request.user.organization).level
        >= OrganizationMembership.Level.ADMIN
    ):
        raise PermissionDenied("You need to be an administrator or owner to access this resource.")

    complete_url = reverse("social:complete", args=("saml",))
    saml_backend = load_backend(load_strategy(request), "saml", redirect_uri=complete_url)
    metadata, errors = saml_backend.generate_metadata_xml()

    if not errors:
        return HttpResponse(content=metadata, content_type="text/xml")


class MultitenantSAMLAuth(SAMLAuth):
    """
    Implements our own version of SAML auth that supports multitenancy. Instead of relying on instance-based config via env vars,
    each organization can have multiple verified domains each with its own SAML configuration.
    """

    def auth_complete(self, *args, **kwargs):
        try:
            return super().auth_complete(*args, **kwargs)
        except Exception:
            import json

            posthoganalytics.tag("request_data", json.dumps(self.strategy.request_data()))
            raise

    def get_idp(self, organization_domain_or_id: Union["OrganizationDomain", str]):
        try:
            organization_domain = (
                organization_domain_or_id
                if isinstance(organization_domain_or_id, OrganizationDomain)
                else OrganizationDomain.objects.verified_domains().get(id=organization_domain_or_id)
            )
        except (OrganizationDomain.DoesNotExist, DjangoValidationError):
            raise AuthFailed(self, "Authentication request is invalid. Invalid RelayState.")

        if not organization_domain.organization.is_feature_available(AvailableFeature.SAML):
            raise AuthFailed(
                self,
                "Your organization does not have the required license to use SAML.",
            )

        return SAMLIdentityProvider(
            str(organization_domain.id),
            entity_id=organization_domain.saml_entity_id,
            url=organization_domain.saml_acs_url,
            x509cert=organization_domain.saml_x509_cert,
        )

    def auth_url(self):
        """
        Overridden to use the config from the relevant OrganizationDomain
        Get the URL to which we must redirect in order to
        authenticate the user
        """
        email = self.strategy.request_data().get("email")

        if not email:
            raise AuthMissingParameter(self, "email")

        instance = OrganizationDomain.objects.get_verified_for_email_address(email=email)

        if not instance or not instance.has_saml:
            raise AuthFailed(self, "SAML not configured for this user.")

        auth = self._create_saml_auth(idp=self.get_idp(instance))
        # Below, return_to sets the RelayState, which contains the ID of
        # the `OrganizationDomain`.  We use it to store the specific SAML IdP
        # name, since we multiple IdPs share the same auth_complete URL.
        return auth.login(return_to=str(instance.id))

    def _get_attr(
        self,
        response_attributes: dict[str, Any],
        attribute_names: list[str],
        optional: bool = False,
    ) -> str:
        """
        Fetches a specific attribute from the SAML response, attempting with multiple different attribute names.
        We attempt multiple attribute names to make it easier for admins to configure SAML (less configuration to set).
        """
        output = None
        for _attr in attribute_names:
            if _attr in response_attributes:
                output = response_attributes[_attr]
                break

        if not output and not optional:
            raise AuthMissingParameter(self, attribute_names[0])

        if isinstance(output, list):
            output = output[0]

        return output

    def get_user_details(self, response):
        """
        Overridden to find attributes across multiple possible names.
        """
        attributes = response["attributes"]
        return {
            "fullname": self._get_attr(
                attributes,
                ["full_name", "FULL_NAME", "fullName", OID_COMMON_NAME],
                optional=True,
            ),
            "first_name": self._get_attr(
                attributes,
                [
                    "first_name",
                    "FIRST_NAME",
                    "firstName",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
                    OID_GIVEN_NAME,
                ],
                optional=True,
            ),
            "last_name": self._get_attr(
                attributes,
                [
                    "last_name",
                    "LAST_NAME",
                    "lastName",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
                    OID_SURNAME,
                ],
                optional=True,
            ),
            "email": self._get_attr(
                attributes,
                [
                    "email",
                    "EMAIL",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                    OID_MAIL,
                ],
            ),
        }

    def get_user_id(self, details, response):
        """
        Overridden to find user ID across multiple attribute names.
        Get the permanent ID for this user from the response.
        """
        USER_ID_ATTRIBUTES = ["name_id", "NAME_ID", "nameId", OID_USERID]
        uid = self._get_attr(response["attributes"], USER_ID_ATTRIBUTES)
        return f"{response['idp_name']}:{uid}"


class CustomGoogleOAuth2(GoogleOAuth2):
    def auth_extra_arguments(self):
        extra_args = super().auth_extra_arguments()
        email = self.strategy.request.GET.get("email")

        if email:
            extra_args["login_hint"] = email

        return extra_args

    def get_user_id(self, details, response):
        """
        Retrieve and migrate Google OAuth user identification.

        Note: While social-auth-core supports using Google's sub claim via
        settings.USE_UNIQUE_USER_ID = True, this setting was not enabled historically
        in our application. This led to emails being stored as uids instead of the
        more stable Google sub identifier.

        'sub' (subject identifier) is part of OpenID Connect and is guaranteed to be a
        stable, unique identifier for the user within Google's system. It's designed
        specifically for authentication purposes and won't change even if the user changes
        their email or other profile details.

        This method handles two types of user identification:
        1. Legacy users: Originally stored with email as their uid (due to missing USE_UNIQUE_USER_ID)
        2. New users: Using Google's sub claim (unique identifier) as uid

        The method first checks if a user exists with the sub as uid. If not found,
        it looks for a legacy user with email as uid and migrates them to use sub.
        This ensures a smooth transition from email-based to sub-based identification
        while maintaining backward compatibility.

        Args:
            details: User details dictionary from OAuth response
            response: Full OAuth response from Google

        Returns:
            str: The Google sub claim to be used as uid
        """
        email = response.get("email")
        sub = response.get("sub")

        if not sub:
            raise ValueError("Google OAuth response missing 'sub' claim")

        try:
            # First try: Find user by sub (preferred method)
            social_auth = UserSocialAuth.objects.get(provider="google-oauth2", uid=sub)
            return sub
        except UserSocialAuth.DoesNotExist:
            pass

        try:
            # Second try: Find and migrate legacy user using email as uid
            social_auth = UserSocialAuth.objects.get(provider="google-oauth2", uid=email)
            # Migrate user from email to sub
            social_auth.uid = sub
            social_auth.save()
            return sub
        except UserSocialAuth.DoesNotExist:
            # No existing user found - use sub for new account
            return sub


logger = structlog.get_logger(__name__)


class VercelAuthentication(authentication.BaseAuthentication):
    """
    Implements Vercel Marketplace API authentication.
    This authentication uses the OpenID Connect Protocol (OIDC).
    Vercel sends a JSON web token (JWT) signed with Vercel’s private key and verifiable
    using Vercel’s public JSON Web Key Sets (JWKS) available through VERCEL_JWKS_URL

    For detailed reference of User/System Auth OIDC token claims schema, see:
    https://vercel.com/docs/integrations/create-integration/marketplace-api#marketplace-partner-api-authentication
    """

    VercelAuthType = Literal["user", "system"]

    VERCEL_AUTH_TYPES: tuple[VercelAuthType, ...] = ("user", "system")
    USER_SUB_RE = re.compile(r"^account:[0-9a-fA-F]+:user:[0-9a-fA-F]+$")
    SYSTEM_SUB_RE = re.compile(r"^account:[0-9a-fA-F]+$")
    VERCEL_ISSUER = "https://marketplace.vercel.com"

    def authenticate(self, request: Request) -> tuple[VercelUser, None] | None:
        token = self._get_bearer_token(request)
        if not token:
            raise AuthenticationFailed("Missing Token for Vercel request")

        auth_type = self._get_vercel_auth_type(request)

        try:
            payload = self._validate_jwt_token(token, auth_type)
            return VercelUser(claims=payload), None
        except jwt.InvalidTokenError as e:
            logger.warning("Vercel auth failed", auth_type=auth_type, error=str(e), integration="vercel")
            raise AuthenticationFailed(f"Invalid {auth_type} authentication token")
        except Exception as e:
            logger.exception("Vercel auth error", auth_type=auth_type, error=str(e), integration="vercel")
            raise AuthenticationFailed(f"{auth_type.title()} authentication failed")

    def _get_bearer_token(self, request: Request) -> str | None:
        if auth_header := request.META.get("HTTP_AUTHORIZATION"):
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1]

        return None

    def _get_vercel_auth_type(self, request: Request) -> "VercelAuthentication.VercelAuthType":
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()

        if auth_type not in self.VERCEL_AUTH_TYPES:
            raise AuthenticationFailed("Missing or invalid X-Vercel-Auth header")

        return cast("VercelAuthentication.VercelAuthType", auth_type)

    def _validate_jwt_token(self, token: str, auth_type: "VercelAuthentication.VercelAuthType") -> VercelClaims:
        payload = self._decode_token(token)
        return self._validate_claims(payload, auth_type)

    def _validate_claims(
        self, payload: dict[str, Any], auth_type: "VercelAuthentication.VercelAuthType"
    ) -> VercelClaims:
        required_claims = ["iss", "sub", "aud"]

        for claim in required_claims:
            if claim not in payload:
                raise jwt.InvalidTokenError(f"Missing required claim: {claim}")

        if payload["iss"] != self.VERCEL_ISSUER:
            raise jwt.InvalidTokenError(f"Invalid issuer: {payload['iss']}")

        if auth_type == "user":
            self._validate_user_claims(payload)

            return VercelUserClaims(
                iss=payload["iss"],
                sub=payload["sub"],
                aud=payload["aud"],
                account_id=payload["account_id"],
                installation_id=payload["installation_id"],
                user_id=payload["user_id"],
                user_role=payload["user_role"],
                type=payload.get("type"),
                user_avatar_url=payload.get("user_avatar_url"),
                user_name=payload.get("user_name"),
                user_email=payload.get("user_email"),
            )
        elif auth_type == "system":
            self._validate_system_claims(payload)

            return VercelSystemClaims(
                iss=payload["iss"],
                sub=payload["sub"],
                aud=payload["aud"],
                account_id=payload["account_id"],
                installation_id=payload["installation_id"],
                type=payload.get("type"),
            )

    def _validate_user_claims(self, payload: dict[str, Any]) -> None:
        self._require_claims(payload, ["account_id", "installation_id", "user_id", "user_role"], "user")

        if not self.USER_SUB_RE.match(payload["sub"]):
            raise jwt.InvalidTokenError(f"Invalid User auth sub format: {payload['sub']}")

        if payload.get("user_role") not in ["ADMIN", "USER"]:
            raise jwt.InvalidTokenError(f"Invalid user_role: {payload.get('user_role')}")

    def _validate_system_claims(self, payload: dict[str, Any]) -> None:
        self._require_claims(payload, ["account_id", "installation_id"], "system")

        sub = payload.get("sub", "")
        if sub and not self.SYSTEM_SUB_RE.match(sub):
            raise jwt.InvalidTokenError(f"Invalid System auth sub format: {sub}")

    def _require_claims(self, payload: dict[str, Any], claims: list[str], auth_type: str = "") -> None:
        missing_claims = set(claims) - set(payload.keys())
        if missing_claims:
            claim_name = next(iter(missing_claims))
            msg = f"Missing required {auth_type + ' ' if auth_type else ''}claim: {claim_name}"
            raise jwt.InvalidTokenError(msg)

    def _decode_token(self, token: str) -> dict[str, Any]:
        jwks = get_vercel_jwks()
        kid = jwt.get_unverified_header(token).get("kid")
        if not kid:
            raise jwt.InvalidTokenError("Token missing key ID")

        try:
            key = RSAAlgorithm.from_jwk(next(k for k in jwks["keys"] if k.get("kid") == kid))
        except StopIteration:
            raise jwt.InvalidTokenError(f"Unable to find key with ID: {kid}")

        if not settings.VERCEL_CLIENT_INTEGRATION_ID:
            raise jwt.InvalidTokenError("VERCEL_CLIENT_INTEGRATION_ID not configured")

        return jwt.decode(
            token,
            key,  # type: ignore  # RSAAlgorithm.from_jwk returns RSAPrivateKey | RSAPublicKey, but jwt.decode accepts both
            algorithms=["RS256"],
            issuer=self.VERCEL_ISSUER,
            audience=settings.VERCEL_CLIENT_INTEGRATION_ID,
            leeway=10,  # account for clock skew with 10 seconds of leeway
        )


def social_auth_allowed(backend, details, response, *args, **kwargs) -> None:
    email = details.get("email")
    # Check if SSO enforcement is enabled for this email address
    sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(email)
    if sso_enforcement is None or sso_enforcement == backend.name:
        return

    if sso_enforcement == "saml":
        raise AuthFailed(backend, "saml_sso_enforced")
    elif sso_enforcement == "google-oauth2":
        raise AuthFailed(backend, "google_sso_enforced")
    elif sso_enforcement == "github":
        raise AuthFailed(backend, "github_sso_enforced")
    elif sso_enforcement == "gitlab":
        raise AuthFailed(backend, "gitlab_sso_enforced")
    else:
        # catch-all in case we missed a case above
        raise AuthFailed(backend, "sso_enforced", email)
