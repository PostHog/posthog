import socket
from typing import Literal

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metabase import (
    MetabaseAuthMethodConfig,
    MetabaseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.metabase import (
    API_KEY_AUTH,
    SESSION_AUTH,
    MetabaseAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.source import MetabaseSource


def _config(selection: Literal["api_key", "session"] = "api_key", **auth_kwargs) -> MetabaseSourceConfig:
    return MetabaseSourceConfig(
        host="https://company.metabaseapp.com",
        auth_method=MetabaseAuthMethodConfig(selection=selection, **auth_kwargs),
    )


class TestMetabaseSource:
    def setup_method(self):
        self.source = MetabaseSource()
        self.team_id = 123
        self.config = _config(api_key="mb_secret")

    def test_dns_resolution_failure_message_is_classified_non_retryable(self):
        # `_is_host_safe` raises this exact message when the Instance URL doesn't resolve via
        # DNS — a permanent, deterministic failure until it's corrected. Build the message via
        # the real `_is_host_safe` code path (not a hand-typed copy) so this test breaks if
        # either side's wording drifts from the classifier's key.
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.get_instance_region",
                return_value="US",
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
                side_effect=socket.gaierror,
            ),
        ):
            ok, err = _is_host_safe("nonexistent.example", team_id=999)

        assert not ok
        assert err is not None
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in err for key in non_retryable)

    @pytest.mark.parametrize(
        "selection, auth_kwargs, expected",
        [
            (API_KEY_AUTH, {"api_key": "mb_x"}, ("mb_x", None, None)),
            (SESSION_AUTH, {"username": "me@x.com", "password": "pw"}, (None, "me@x.com", "pw")),
        ],
    )
    def test_build_auth(self, selection, auth_kwargs, expected):
        auth = self.source._build_auth(_config(selection, **auth_kwargs))
        assert isinstance(auth, MetabaseAuth)
        assert auth.method == selection
        assert (auth.api_key, auth.username, auth.password) == expected
