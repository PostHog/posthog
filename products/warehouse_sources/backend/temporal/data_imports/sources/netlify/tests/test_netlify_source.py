from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.netlify import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.source import NetlifySource


class TestNetlifyGetSchemas:
    def test_names_filter(self) -> None:
        schemas = NetlifySource().get_schemas(mock.Mock(), team_id=1, names=["sites", "deploys"])
        assert {s.name for s in schemas} == {"sites", "deploys"}


class TestNetlifyValidateCredentials:
    def test_failure(self) -> None:
        with mock.patch.object(source_module, "validate_netlify_credentials", return_value=(False, "nope")):
            ok, error = NetlifySource().validate_credentials(mock.Mock(), team_id=1)
        assert ok is False
        assert error == "nope"
