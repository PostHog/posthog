from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.netlify import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.source import NetlifySource


class TestNetlifyGetSchemas:
    def test_all_endpoints_full_refresh(self) -> None:
        schemas = NetlifySource().get_schemas(mock.Mock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Netlify has no server-side timestamp filter, so no table supports incremental/append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_names_filter(self) -> None:
        schemas = NetlifySource().get_schemas(mock.Mock(), team_id=1, names=["sites", "deploys"])
        assert {s.name for s in schemas} == {"sites", "deploys"}


class TestNetlifyValidateCredentials:
    def test_success(self) -> None:
        with mock.patch.object(source_module, "validate_netlify_credentials", return_value=True):
            assert NetlifySource().validate_credentials(mock.Mock(), team_id=1) == (True, None)

    def test_failure(self) -> None:
        with mock.patch.object(source_module, "validate_netlify_credentials", return_value=False):
            ok, error = NetlifySource().validate_credentials(mock.Mock(), team_id=1)
        assert ok is False
        assert error is not None
