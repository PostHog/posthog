from types import SimpleNamespace
from typing import cast

from parameterized import parameterized
from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_EU,
    POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_US,
)

from products.tasks.backend.facade.client_provenance import get_task_client_provenance
from products.tasks.backend.models import TaskClientProvenance


class TestTaskClientProvenance:
    @parameterized.expand(
        [
            (
                "desktop",
                OAuthAccessTokenAuthentication,
                ARRAY_APP_CLIENT_ID_DEV,
                True,
                "task:write",
                True,
            ),
            (
                "mobile_us",
                OAuthAccessTokenAuthentication,
                POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_US,
                True,
                "task:write",
                True,
            ),
            (
                "mobile_eu",
                OAuthAccessTokenAuthentication,
                POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_EU,
                True,
                "task:write",
                True,
            ),
            (
                "other_oauth",
                OAuthAccessTokenAuthentication,
                "other-client",
                True,
                "task:write",
                False,
            ),
            (
                "internal_desktop_app_token",
                OAuthAccessTokenAuthentication,
                ARRAY_APP_CLIENT_ID_DEV,
                True,
                "task:write internal_run:read",
                False,
            ),
            (
                "server_token_without_internal_scope",
                OAuthAccessTokenAuthentication,
                ARRAY_APP_CLIENT_ID_DEV,
                False,
                "task:write",
                False,
            ),
            (
                "personal_api_key",
                PersonalAPIKeyAuthentication,
                ARRAY_APP_CLIENT_ID_DEV,
                True,
                "task:write",
                False,
            ),
        ]
    )
    def test_derives_only_trusted_desktop_oauth(
        self,
        _name: str,
        authenticator_type: type,
        client_id: str,
        has_authorization_flow_lineage: bool,
        scope: str,
        expected_desktop: bool,
    ) -> None:
        authenticator = authenticator_type()
        authenticator.access_token = SimpleNamespace(
            application=SimpleNamespace(client_id=client_id),
            source_refresh_token_id="refresh-token-id" if has_authorization_flow_lineage else None,
            scope=scope,
        )
        request = cast(Request, SimpleNamespace(successful_authenticator=authenticator))

        provenance = get_task_client_provenance(request)

        assert (provenance == TaskClientProvenance.POSTHOG_DESKTOP) is expected_desktop

    def test_missing_authentication_provenance_fails_closed(self) -> None:
        assert get_task_client_provenance(cast(Request, SimpleNamespace())) is None
