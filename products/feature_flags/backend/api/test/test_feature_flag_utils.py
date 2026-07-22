from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.property import Property

from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty
from products.cohorts.backend.models.util import sort_cohorts_topologically
from products.feature_flags.backend.api.feature_flag import _describe_behavioral_properties


class TestFeatureFlagUtils(APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_cohorts_sorted_topologically(self):
        cohorts = {}

        def create_cohort(name):
            cohorts[name] = Cohort.objects.create(
                team=self.team,
                name=name,
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "name", "value": "test", "type": "person"},
                        ],
                    }
                },
            )

        create_cohort("a")
        create_cohort("b")
        create_cohort("c")

        # (c)-->(b)
        cohorts["c"].filters["properties"]["values"][0] = {
            "key": "id",
            "value": cohorts["b"].pk,
            "type": "cohort",
            "negation": True,
        }
        cohorts["c"].save()

        # (a)-->(c)
        cohorts["a"].filters["properties"]["values"][0] = {
            "key": "id",
            "value": cohorts["c"].pk,
            "type": "cohort",
            "negation": True,
        }
        cohorts["a"].save()

        cohort_ids = {cohorts["a"].pk, cohorts["b"].pk, cohorts["c"].pk}
        seen_cohorts_cache = {
            cohorts["a"].pk: cohorts["a"],
            cohorts["b"].pk: cohorts["b"],
            cohorts["c"].pk: cohorts["c"],
        }

        # (a)-->(c)-->(b)
        # create b first, since it doesn't depend on any other cohorts
        # then c, because it depends on b
        # then a, because it depends on c

        # thus destination creation order: b, c, a
        destination_creation_order = [cohorts["b"].pk, cohorts["c"].pk, cohorts["a"].pk]
        topologically_sorted_cohort_ids = sort_cohorts_topologically(cohort_ids, seen_cohorts_cache)
        self.assertEqual(topologically_sorted_cohort_ids, destination_creation_order)

    def test_empty_cohorts_set(self):
        cohort_ids: set[int] = set()
        seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
        topologically_sorted_cohort_ids = sort_cohorts_topologically(cohort_ids, seen_cohorts_cache)
        self.assertEqual(topologically_sorted_cohort_ids, [])


def _behavioral_prop(key: str) -> Property:
    return Property(
        key=key, type="behavioral", value="performed_event", event_type="events", time_value=30, time_interval="day"
    )


class TestDescribeBehavioralProperties(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_properties", [], None),
            ("single_property", [_behavioral_prop("$pageview")], "'$pageview' (performed_event)"),
            (
                "two_distinct_properties",
                [_behavioral_prop("$pageview"), _behavioral_prop("$autocapture")],
                "'$pageview' (performed_event) and 1 other",
            ),
            (
                "three_distinct_properties",
                [_behavioral_prop("$pageview"), _behavioral_prop("$autocapture"), _behavioral_prop("$identify")],
                "'$pageview' (performed_event) and 2 others",
            ),
            (
                "duplicate_properties_collapse_to_one",
                [_behavioral_prop("$pageview"), _behavioral_prop("$pageview")],
                "'$pageview' (performed_event)",
            ),
        ]
    )
    def test_describes_behavioral_properties(self, _name, behavioral_props, expected):
        self.assertEqual(_describe_behavioral_properties(behavioral_props), expected)
