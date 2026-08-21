from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty import source as zenduty_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zenduty.source import ZendutySource


class TestZendutyGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = ZendutySource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_endpoints_are_full_refresh(self) -> None:
        # Zenduty exposes no confirmed universal server-side updated-since filter, so nothing is
        # advertised as incremental — a client-side cursor is not incremental.
        schemas = ZendutySource().get_schemas(MagicMock(), team_id=1)
        assert all(s.supports_incremental is False and s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_names_filter(self) -> None:
        schemas = ZendutySource().get_schemas(MagicMock(), team_id=1, names=["incidents", "services"])
        assert {s.name for s in schemas} == {"incidents", "services"}


class TestZendutyValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # Zenduty returns 403 (not 401) for a bad/inactive token — reject even at source-create.
            ("forbidden_is_bad_token", 403, False),
            ("unauthorized_rejected", 401, False),
            ("connection_failure_rejected", None, False),
            ("unexpected_status_rejected", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, probe_status: int | None, expected_ok: bool) -> None:
        with mock.patch.object(zenduty_source_module, "probe_credentials", return_value=probe_status):
            ok, error = ZendutySource().validate_credentials(MagicMock(api_key="tok"), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
