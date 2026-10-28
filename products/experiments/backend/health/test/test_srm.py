from dataclasses import replace

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.facade.contracts import ExperimentHealthFinding
from products.experiments.backend.health.checks.srm import SEGMENT_MISMATCH, srm
from products.experiments.backend.health.context import ExposureSegment, ExposureTotals
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension

LIBRARY = ExposureSegmentDimension.LIBRARY
PAGE = ExposureSegmentDimension.PAGE
MISMATCH = "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001)."
NO_LOCATION = f"{MISMATCH} This may indicate issues with randomization or data collection."
NEXT_STEP = "Check that the code there sends the exposure for every user in every variant."


def _segment(dimension: ExposureSegmentDimension, value: str, control: int, test: int) -> ExposureSegment:
    return ExposureSegment(dimension=dimension, value=value, exposed_by_variant={"control": control, "test": test})


def _exposures(segments: tuple[ExposureSegment, ...] | None) -> ExposureTotals:
    return ExposureTotals(
        total_exposures={"control": 600, "test": 900},
        multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
        sample_ratio_mismatch_p_value=0.00001,
        sample_ratio_expected={"control": 750, "test": 750},
        daily_exposures={},
        hours_since_launch=72,
        counts_groups=False,
        segments=segments,
    )


SERVER_SKEWED = (
    _segment(LIBRARY, "web", 500, 500),
    _segment(LIBRARY, "posthog-node", 100, 400),
    _segment(PAGE, "/pricing", 300, 300),
    _segment(PAGE, "/checkout", 200, 200),
)


class TestSrmSegments(TestCase):
    @parameterized.expand(
        [
            (
                "server_library",
                SERVER_SKEWED,
                SEGMENT_MISMATCH,
                f'{MISMATCH} The mismatch comes from users whose first exposure was sent by the "posthog-node" library. '
                f'Users whose first exposure was sent by the "web" library match the split (p = 1). {NEXT_STEP}',
            ),
            (
                "one_page",
                (
                    _segment(LIBRARY, "web", 500, 800),
                    _segment(PAGE, "/pricing", 300, 300),
                    _segment(PAGE, "/checkout", 100, 400),
                    _segment(PAGE, BREAKDOWN_OTHER_STRING_LABEL, 100, 100),
                ),
                SEGMENT_MISMATCH,
                f"{MISMATCH} The mismatch comes from users first exposed on the page /checkout. Users first exposed on "
                f"the page /pricing and other pages match the split. {NEXT_STEP}",
            ),
            (
                "every_library",
                (_segment(LIBRARY, "web", 300, 450), _segment(LIBRARY, "posthog-node", 300, 450)),
                None,
                NO_LOCATION,
            ),
            (
                "too_few_to_compare",
                (_segment(LIBRARY, "web", 40, 50), _segment(LIBRARY, "posthog-node", 560, 850)),
                None,
                NO_LOCATION,
            ),
            ("segments_not_loaded", None, None, NO_LOCATION),
        ]
    )
    def test_names_the_segment_with_the_mismatch(
        self, _name: str, segments: tuple[ExposureSegment, ...] | None, subcode: str | None, detail: str
    ) -> None:
        outcome = srm(replace(RUNNING_CONTEXT, exposures=_exposures(segments)))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(
            (outcome.subcode, outcome.title, outcome.detail),
            (subcode, "Users are not split across variants as configured", detail),
        )

    def test_puts_every_segment_in_the_evidence(self) -> None:
        outcome = srm(replace(RUNNING_CONTEXT, exposures=_exposures(SERVER_SKEWED)))

        assert isinstance(outcome, ExperimentHealthFinding)
        evidence = dict(outcome.evidence)
        server_p_value = evidence.pop("library_2_p_value")
        assert isinstance(server_p_value, float)
        self.assertLess(server_p_value, 0.001)
        self.assertEqual(
            evidence,
            {
                "p_value": 0.00001,
                "library_1": "web",
                "library_1_p_value": 1.0,
                "library_1_exposed_control": 500,
                "library_1_exposed_test": 500,
                "library_2": "posthog-node",
                "library_2_exposed_control": 100,
                "library_2_exposed_test": 400,
                "page_1": "/pricing",
                "page_1_p_value": 1.0,
                "page_1_exposed_control": 300,
                "page_1_exposed_test": 300,
                "page_2": "/checkout",
                "page_2_p_value": 1.0,
                "page_2_exposed_control": 200,
                "page_2_exposed_test": 200,
            },
        )
