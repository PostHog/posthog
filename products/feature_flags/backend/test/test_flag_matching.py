from unittest.mock import MagicMock, PropertyMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.flag_matching import FeatureFlagMatcher, FeatureFlagMatchReason


def _make_matcher(query_conditions: dict[str, bool]) -> FeatureFlagMatcher:
    matcher = FeatureFlagMatcher(
        team_id=1,
        project_id=1,
        feature_flags=[],
        distinct_id="test",
    )
    return matcher


def _make_flag(pk: int = 42, key: str = "test-flag") -> MagicMock:
    flag = MagicMock()
    flag.pk = pk
    flag.key = key
    return flag


class TestIsFeatureEnrollmentMatch(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "enrollment_is_set_true_and_matches",
                {"flag_42_enrollment_is_set": True, "flag_42_enrollment": True},
                (True, True, FeatureFlagMatchReason.SUPER_CONDITION_VALUE),
            ),
            (
                "enrollment_is_set_true_but_not_matching",
                {"flag_42_enrollment_is_set": True, "flag_42_enrollment": False},
                (True, False, FeatureFlagMatchReason.SUPER_CONDITION_VALUE),
            ),
            (
                "enrollment_is_set_false",
                {"flag_42_enrollment_is_set": False, "flag_42_enrollment": False},
                (False, False, FeatureFlagMatchReason.NO_CONDITION_MATCH),
            ),
            (
                "enrollment_query_missing",
                {},
                (False, False, FeatureFlagMatchReason.NO_CONDITION_MATCH),
            ),
        ],
    )
    def test_is_feature_enrollment_match(
        self,
        _name: str,
        query_conditions: dict[str, bool],
        expected: tuple[bool, bool, FeatureFlagMatchReason],
    ):
        matcher = _make_matcher(query_conditions)
        flag = _make_flag()
        with patch.object(type(matcher), "query_conditions", new_callable=PropertyMock, return_value=query_conditions):
            result = matcher.is_feature_enrollment_match(flag)
        assert result == expected
