from uuid import UUID

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.release.backend.feature_flags import RELEASES_AREA_FLAG, ReleasesGateUnavailable, is_releases_enabled

TEAM_UUID = UUID("0192c8a4-0000-7000-8000-000000000001")
ORGANIZATION_ID = UUID("0192c8a4-0000-7000-8000-000000000002")


class TestReleasesGate(SimpleTestCase):
    def test_gate_uses_the_browser_group_keys(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
            enabled = is_releases_enabled(
                team_id=7, team_uuid=TEAM_UUID, organization_id=ORGANIZATION_ID, distinct_id="user-1", email=None
            )

        assert enabled is True
        assert feature_enabled.call_args.args[:2] == (RELEASES_AREA_FLAG, "user-1")
        assert feature_enabled.call_args.kwargs["groups"] == {
            "organization": str(ORGANIZATION_ID),
            "project": str(TEAM_UUID),
        }

    @parameterized.expand([("raises", RuntimeError("flags unreachable")), ("cannot_evaluate", None)])
    def test_gate_stays_closed_when_the_flag_service_fails(self, _name: str, failure: Exception | None) -> None:
        side_effect = failure if failure else None
        with (
            patch("posthoganalytics.feature_enabled", side_effect=side_effect, return_value=None),
            patch("posthoganalytics.disabled", False),
        ):
            assert (
                is_releases_enabled(
                    team_id=7, team_uuid=TEAM_UUID, organization_id=ORGANIZATION_ID, distinct_id="u", email=None
                )
                is False
            )
            with pytest.raises((RuntimeError, ReleasesGateUnavailable)):
                is_releases_enabled(
                    team_id=7,
                    team_uuid=TEAM_UUID,
                    organization_id=ORGANIZATION_ID,
                    distinct_id="u",
                    email=None,
                    raise_on_error=True,
                )
