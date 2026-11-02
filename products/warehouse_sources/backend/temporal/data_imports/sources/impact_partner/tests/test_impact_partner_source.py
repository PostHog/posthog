from typing import Optional

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impactpartner import (
    ImpactPartnerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner.source import ImpactPartnerSource


def _driver() -> SourceDriver:
    return SourceDriver(ImpactPartnerSource(), ImpactPartnerSourceConfig(account_sid="s", auth_token="t"))


class TestImpactPartnerSourceClass:
    @parameterized.expand(
        [
            ("Actions", True),
            ("Invoices", True),
            ("Campaigns", False),
        ]
    )
    def test_supports_incremental_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = ImpactPartnerSource().get_schemas(
            ImpactPartnerSourceConfig(account_sid="s", auth_token="t"), team_id=1, names=[endpoint]
        )
        assert len(schemas) == 1
        assert schemas[0].supports_incremental is expected
        assert schemas[0].supports_append is expected

    @parameterized.expand(
        [
            ("valid", True, True, None),
            (
                "invalid",
                False,
                False,
                "Your impact.com Account SID or Auth token isn't valid for a partner account. Check both values, or use the impact.com source for a brand account.",
            ),
        ]
    )
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with scripted_network([ScriptedResponse(status=200 if api_result else 401)]) as network:
            result = ImpactPartnerSource().validate_credentials(
                ImpactPartnerSourceConfig(account_sid="s", auth_token="t"), team_id=1
            )
        assert result == (ok, err)
        # An unpinned source instance validates against the default vendor API version.
        assert network.requests_log[0].headers["ir-version"] == "16"

    @time_machine.travel("2026-06-01", tick=False)
    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = _driver().run(
            "Actions",
            always(ScriptedResponse(json={"Actions": [], "@numpages": "1"})),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].path == "/Mediapartners/s/Actions"
        assert result.requests[0].headers["authorization"] == "Basic czp0"
        assert result.requests[0].headers["ir-version"] == "16"
        assert result.requests[0].param("ActionDateStart") == "2026-01-01T00:00:00Z"

    @time_machine.travel("2026-06-01", tick=False)
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        result = _driver().run(
            "Actions",
            always(ScriptedResponse(json={"Actions": [], "@numpages": "1"})),
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].param("ActionDateStart") == "2023-06-02T00:00:00Z"

    @parameterized.expand(
        [
            (
                "exhausted_429",
                "429 Client Error: Too Many Requests for url: https://api.impact.com/Mediapartners/s/Actions",
            ),
            (
                "exhausted_500",
                "500 Server Error: Internal Server Error for url: https://api.impact.com/Mediapartners/s/Campaigns",
            ),
            ("exhausted_502", "502 Server Error: Bad Gateway for url: https://api.impact.com/Mediapartners/s/Invoices"),
        ]
    )
    def test_exhausted_transient_responses_are_retryable(self, _name: str, error: str) -> None:
        assert error_message_matches(error, ImpactPartnerSource().get_retryable_errors())

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.impact.com/Mediapartners/s/Invoices"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.impact.com/Mediapartners/s/Invoices"),
        ]
    )
    def test_client_errors_are_not_retryable(self, _name: str, error: str) -> None:
        assert not error_message_matches(error, ImpactPartnerSource().get_retryable_errors())
