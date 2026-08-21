from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack import (
    source as better_stack_source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.source import BetterStackSource


class TestBetterStackValidateCredentials:
    @parameterized.expand(
        [
            # (probe status, schema_name, expected_ok)
            ("ok", 200, None, True),
            ("ok_for_schema", 200, "incidents", True),
            # A 403 at source-create is a genuine token scoped away from the probe resource — accept it.
            ("forbidden_at_create_accepted", 403, None, True),
            # A 403 while configuring a specific schema means no access to that resource — reject.
            ("forbidden_for_schema_rejected", 403, "incidents", False),
            ("unauthorized_rejected", 401, None, False),
            ("connection_failure_rejected", None, None, False),
            ("unexpected_status_rejected", 500, None, False),
        ]
    )
    def test_status_mapping(
        self, _name: str, probe_status: int | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        with mock.patch.object(better_stack_source_module, "probe_credentials", return_value=probe_status):
            ok, error = BetterStackSource().validate_credentials(
                MagicMock(api_token="bs_test"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok
