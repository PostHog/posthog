from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from products.feature_flags.backend.user_blast_radius import (
    BlastRadiusResult,
    get_person_blast_radius_v2,
    get_user_blast_radius,
)

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}

GATE = "products.feature_flags.backend.api.feature_flag.use_blast_radius_query_v2"


class TestBlastRadiusQueryV2(ClickhouseTestMixin, APIBaseTest):
    def _create_persons(self, subscribed_flags: list[bool]) -> None:
        for i, subscribed in enumerate(subscribed_flags, start=1):
            _create_person(
                team=self.team,
                distinct_ids=[f"user-{i}"],
                properties={"subscribed": "true" if subscribed else "false"},
            )
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("matching a person property", FILTERS, 3, 4),
            ("with no conditions", {}, 4, 4),
        ]
    )
    def test_sized_condition_matches_the_v1_counts(self, _name, filters, affected, total):
        # A handful of persons never clears MIN_SAMPLED_MATCHES under the default sample, so
        # this exercises the exact fallback and pins both counts to the v1 result.
        self._create_persons([True, True, True, False])

        v1_result = get_user_blast_radius(self.team, filters)
        result = get_person_blast_radius_v2(self.team, filters)

        assert (result.affected, result.total) == (affected, total)
        assert (result.affected, result.total) == (v1_result.affected, v1_result.total)

    def test_sampled_path_extrapolates_by_modulus(self):
        self._create_persons([True, True, False])

        # Modulus 1 samples everyone and MIN_SAMPLED_MATCHES 0 forces the sampled branch,
        # so the extrapolated result must equal the exact count.
        with (
            patch("products.feature_flags.backend.person_sampling.SAMPLE_MODULUS", 1),
            patch("products.feature_flags.backend.person_sampling.MIN_SAMPLED_MATCHES", 0),
        ):
            result = get_person_blast_radius_v2(self.team, FILTERS)

        assert (result.affected, result.total) == (2, 3)

    @parameterized.expand(
        [
            ("person condition, gate on", True, None, True),
            ("person condition, gate off", False, None, False),
            # The sampled count only covers person audiences, so a group condition stays on v1.
            ("group condition, gate on", True, 0, False),
        ]
    )
    def test_endpoint_uses_the_sampled_count_only_for_a_gated_person_condition(
        self, _name, gate_on, group_type_index, expects_v2
    ):
        body: dict = {"condition": {"properties": []}}
        if group_type_index is not None:
            body["group_type_index"] = group_type_index

        with (
            patch(GATE, return_value=gate_on),
            patch("products.feature_flags.backend.api.feature_flag.get_person_blast_radius_v2") as sampled,
            patch("products.feature_flags.backend.api.feature_flag.get_user_blast_radius") as v1,
        ):
            sampled.return_value = BlastRadiusResult(affected=6400, total=64000)
            v1.return_value = BlastRadiusResult(affected=4, total=10)

            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                body,
            )

        assert response.status_code == 200, response.json()
        assert response.json()["affected"] == (6400 if expects_v2 else 4)
        assert sampled.called is expects_v2
