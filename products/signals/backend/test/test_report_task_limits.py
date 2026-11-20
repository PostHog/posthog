from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.report_task_limits import ReportTaskRunLimits, limits_from_payload

USER = "0190f1f0-0000-7000-8000-00000000000a"
ORG = "0190f1f0-0000-7000-8000-00000000000b"

LAYERED = {
    "US": {
        "default": {"per_hour": 25, "per_day": 70},
        "organizations": {ORG: {"per_hour": 30, "per_day": 150}},
        "teams": {"7": {"per_hour": 60}, "5": {"per_hour": 40, "per_day": 200}},
        "users": {USER: {"per_day": 300}},
    }
}


class TestLimitsFromPayload(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_payload", None, "US", ReportTaskRunLimits(per_hour=20, per_day=50)),
            ("empty_payload", {}, "US", ReportTaskRunLimits(per_hour=20, per_day=50)),
            ("no_region_setting", LAYERED, None, ReportTaskRunLimits(per_hour=20, per_day=50)),
            ("entry_under_another_region", LAYERED, "EU", ReportTaskRunLimits(per_hour=20, per_day=50)),
            ("region_is_not_an_object", {"US": [1, 2]}, "US", ReportTaskRunLimits(per_hour=20, per_day=50)),
            # Each field takes the most specific entry that sets it: the user sets only per_day, and the
            # team entry for the request's own team sets only per_hour, ahead of its parent project's entry.
            ("each_field_most_specific", LAYERED, "us", ReportTaskRunLimits(per_hour=60, per_day=300)),
            (
                "clamped_to_ceiling",
                {"US": {"default": {"per_hour": 1000, "per_day": 10_000}}},
                "US",
                ReportTaskRunLimits(per_hour=100, per_day=500),
            ),
            (
                "malformed_values_fall_through",
                {
                    "US": {
                        "default": {"per_hour": 25, "per_day": 70},
                        "users": {USER: {"per_hour": "60", "per_day": 0}},
                        "teams": {"7": {"per_hour": True, "per_day": 2.5}},
                        "organizations": {ORG: {"per_hour": -1}},
                    }
                },
                "US",
                ReportTaskRunLimits(per_hour=25, per_day=70),
            ),
            (
                "malformed_maps_fall_back",
                {"US": {"users": [USER], "teams": {"7": 300}, "default": "lots"}},
                "US",
                ReportTaskRunLimits(per_hour=20, per_day=50),
            ),
        ]
    )
    def test_resolves(self, _name: str, payload: object, region: str | None, expected: ReportTaskRunLimits) -> None:
        assert limits_from_payload(payload, region=region, user_uuid=USER, team_ids=[7, 5], organization_id=ORG) == (
            expected
        )

    @parameterized.expand(
        [
            ("parent_project_entry", [9, 5], ReportTaskRunLimits(per_hour=40, per_day=200)),
            ("team_entry_sets_one_field", [7, 5], ReportTaskRunLimits(per_hour=60, per_day=200)),
            ("organization_entry", [9, None], ReportTaskRunLimits(per_hour=30, per_day=150)),
        ]
    )
    def test_falls_back_to_less_specific_entries(
        self, _name: str, team_ids: list[int | None], expected: ReportTaskRunLimits
    ) -> None:
        assert (
            limits_from_payload(LAYERED, region="US", user_uuid=None, team_ids=team_ids, organization_id=ORG)
            == expected
        )
