from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.netlify import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.source import NetlifySource


class TestNetlifyValidateCredentials:
    def test_failure(self) -> None:
        with mock.patch.object(source_module, "validate_netlify_credentials", return_value=(False, "nope")):
            ok, error = NetlifySource().validate_credentials(mock.Mock(), team_id=1)
        assert ok is False
        assert error == "nope"
