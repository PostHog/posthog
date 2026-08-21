from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.source import RKICovidSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.source"


def _make_config(history_days: int | None = None) -> Any:
    config = MagicMock()
    config.history_days = history_days
    return config


class TestRKICovidSource:
    @parameterized.expand(
        [
            ("no_days_reachable", None, True, True),
            ("valid_days_reachable", 90, True, True),
            ("unreachable", None, False, False),
        ]
    )
    def test_validate_credentials(self, _name: str, days: int | None, probe_result: bool, expected_ok: bool) -> None:
        with patch(f"{MODULE}.validate_connection", return_value=probe_result):
            ok, message = RKICovidSource().validate_credentials(_make_config(days), team_id=1)
        assert ok is expected_ok
        assert (message is None) is expected_ok

    def test_validate_credentials_rejects_invalid_days_without_probing(self) -> None:
        with patch(f"{MODULE}.validate_connection") as probe:
            ok, message = RKICovidSource().validate_credentials(_make_config(0), team_id=1)
        assert ok is False
        assert message is not None and "History window" in message
        probe.assert_not_called()

    def test_source_for_pipeline_plumbs_endpoint_and_history_days(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "germany_history_cases"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.rki_covid_source") as source_fn:
            RKICovidSource().source_for_pipeline(_make_config(30), inputs)
        source_fn.assert_called_once()
        kwargs = source_fn.call_args.kwargs
        assert kwargs["endpoint"] == "germany_history_cases"
        assert kwargs["history_days"] == 30

    def test_source_for_pipeline_rejects_invalid_history_days(self) -> None:
        # A previously-saved bad config must fail the run loudly instead of syncing a wrong window.
        inputs = MagicMock()
        inputs.schema_name = "germany_history_cases"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.rki_covid_source") as source_fn:
            with pytest.raises(ValueError, match="History window"):
                RKICovidSource().source_for_pipeline(_make_config(-1), inputs)
        source_fn.assert_not_called()
