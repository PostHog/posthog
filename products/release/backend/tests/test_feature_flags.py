from uuid import UUID

from unittest.mock import patch

from django.test import SimpleTestCase

from products.release.backend.feature_flags import RELEASES_AREA_FLAG, is_releases_enabled

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

    def test_gate_stays_closed_when_the_flag_service_fails(self) -> None:
        with patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flags unreachable")):
            assert (
                is_releases_enabled(
                    team_id=7, team_uuid=TEAM_UUID, organization_id=ORGANIZATION_ID, distinct_id="user-1", email=None
                )
                is False
            )
