from types import SimpleNamespace

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.client_provenance import get_task_client_provenance
from products.tasks.backend.models import TaskClientProvenance


class TestTaskClientProvenance:
    @parameterized.expand(
        [
            ("desktop", OAuthAccessTokenAuthentication, ARRAY_APP_CLIENT_ID_DEV, "task:write", True),
            ("other_oauth", OAuthAccessTokenAuthentication, "other-client", "task:write", False),
            (
                "internal_desktop_app_token",
                OAuthAccessTokenAuthentication,
                ARRAY_APP_CLIENT_ID_DEV,
                "task:write internal_run:read",
                False,
            ),
            ("personal_api_key", PersonalAPIKeyAuthentication, ARRAY_APP_CLIENT_ID_DEV, "task:write", False),
        ]
    )
    def test_derives_only_trusted_desktop_oauth(
        self,
        _name: str,
        authenticator_type: type,
        client_id: str,
        scope: str,
        expected_desktop: bool,
    ) -> None:
        authenticator = authenticator_type()
        authenticator.access_token = SimpleNamespace(
            application=SimpleNamespace(client_id=client_id),
            scope=scope,
        )
        request = SimpleNamespace(successful_authenticator=authenticator)

        provenance = get_task_client_provenance(request)

        assert (provenance == TaskClientProvenance.POSTHOG_DESKTOP) is expected_desktop

    def test_missing_authentication_provenance_fails_closed(self) -> None:
        assert get_task_client_provenance(SimpleNamespace()) is None
