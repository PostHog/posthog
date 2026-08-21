from typing import Literal

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.grafana import (
    GrafanaAuthMethodConfig,
    GrafanaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.grafana import (
    BASIC_AUTH,
    TOKEN_AUTH,
    GrafanaAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source import GrafanaSource


def _config(selection: Literal["token", "basic"] = "token", **auth_kwargs) -> GrafanaSourceConfig:
    return GrafanaSourceConfig(
        host="https://yourstack.grafana.net",
        auth_method=GrafanaAuthMethodConfig(selection=selection, **auth_kwargs),
    )


class TestGrafanaSource:
    def setup_method(self):
        self.source = GrafanaSource()
        self.team_id = 123
        self.config = _config(token="glsa_secret")

    @pytest.mark.parametrize(
        "selection, auth_kwargs, expected",
        [
            (TOKEN_AUTH, {"token": "glsa_x"}, ("glsa_x", None, None)),
            (BASIC_AUTH, {"username": "admin", "password": "pw"}, (None, "admin", "pw")),
        ],
    )
    def test_build_auth(self, selection, auth_kwargs, expected):
        auth = self.source._build_auth(_config(selection, **auth_kwargs))
        assert isinstance(auth, GrafanaAuth)
        assert auth.method == selection
        assert (auth.token, auth.username, auth.password) == expected
