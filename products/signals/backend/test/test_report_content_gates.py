from collections.abc import Callable
from uuid import UUID

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import posthoganalytics
from parameterized import parameterized

from products.signals.backend.report_content_gates import (
    organization_report_metrics_enabled,
    organization_report_monitoring_enabled,
    team_first_report_email_enabled,
    team_report_metrics_enabled,
    team_report_monitoring_enabled,
)

_TEAM_LOOKUP = "products.signals.backend.report_content_gates.Team.objects.values_list"
_FLAG_EVALUATION = "products.signals.backend.report_content_gates.feature_enabled_or_false"


class TestReportContentGates(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{name}_{debug}_{enabled}", gate, flag, local, debug, enabled)
            for name, gate, flag, local in [
                ("monitoring", team_report_monitoring_enabled, "signals-report-monitoring", True),
                ("first_report_email", team_first_report_email_enabled, "signals-first-report-email", False),
            ]
            for debug in [False, True]
            for enabled in [False, True]
        ]
    )
    def test_lifecycle_feature_requires_the_organization_flag(
        self, _name: str, gate: Callable[[int], bool], flag: str, local: bool, debug: bool, enabled: bool
    ) -> None:
        organization_id = UUID("00000000-0000-0000-0000-000000000001")
        with (
            override_settings(DEBUG=debug),
            patch(_TEAM_LOOKUP) as team_lookup,
            patch(_FLAG_EVALUATION, return_value=enabled) as evaluate,
        ):
            team_lookup.return_value.get.return_value = organization_id

            assert gate(7) is enabled

        team_lookup.return_value.get.assert_called_once_with(id=7)
        evaluate.assert_called_once_with(
            flag,
            str(organization_id),
            groups={"organization": str(organization_id)},
            group_properties={"organization": {"id": str(organization_id)}},
            send_feature_flag_events=False,
            only_evaluate_locally=local,
        )

    @override_settings(DEBUG=False)
    def test_missing_local_monitoring_flag_fails_closed_without_changing_metrics(self) -> None:
        organization_id = UUID("00000000-0000-0000-0000-000000000001")
        sdk = posthoganalytics.Client("phc_test_monitoring", send=False, enable_local_evaluation=False)
        sdk.feature_flags = []
        self.addCleanup(sdk.shutdown)
        with (
            patch.multiple(posthoganalytics, default_client=sdk, disabled=False),
            patch(
                "posthoganalytics.client.flags", return_value={"featureFlags": {"signals-report-metrics": True}}
            ) as remote_flags,
        ):
            assert not organization_report_monitoring_enabled(organization_id)
            remote_flags.assert_not_called()
            assert organization_report_metrics_enabled(organization_id)
            remote_flags.assert_called_once()

    @parameterized.expand(
        [("monitoring", team_report_monitoring_enabled), ("first_report_email", team_first_report_email_enabled)]
    )
    @override_settings(DEBUG=True)
    def test_lifecycle_feature_fails_closed_when_flag_evaluation_fails(
        self, _name: str, gate: Callable[[int], bool]
    ) -> None:
        with patch(_TEAM_LOOKUP) as team_lookup, patch(_FLAG_EVALUATION, side_effect=RuntimeError("unavailable")):
            team_lookup.return_value.get.return_value = UUID("00000000-0000-0000-0000-000000000001")

            assert not gate(7)

    @parameterized.expand(
        [("monitoring", team_report_monitoring_enabled), ("first_report_email", team_first_report_email_enabled)]
    )
    @override_settings(DEBUG=True)
    def test_lifecycle_feature_fails_closed_when_the_team_cannot_be_read(
        self, _name: str, gate: Callable[[int], bool]
    ) -> None:
        with (
            patch(_TEAM_LOOKUP, side_effect=RuntimeError("unavailable")),
            patch(_FLAG_EVALUATION) as evaluate,
        ):
            assert not gate(7)

        evaluate.assert_not_called()

    @override_settings(DEBUG=True)
    def test_metrics_keep_the_existing_debug_override(self) -> None:
        with patch(_TEAM_LOOKUP) as team_lookup, patch(_FLAG_EVALUATION) as evaluate:
            assert team_report_metrics_enabled(7)

        team_lookup.assert_not_called()
        evaluate.assert_not_called()
