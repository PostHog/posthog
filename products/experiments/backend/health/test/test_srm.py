from dataclasses import replace

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.facade.contracts import ExperimentHealthFinding
from products.experiments.backend.health.checks.srm import srm
from products.experiments.backend.health.context import ExposureSegment, ExposureTotals
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension

LIBRARY = ExposureSegmentDimension.LIBRARY
LIBRARY_VERSION = ExposureSegmentDimension.LIBRARY_VERSION
PAGE = ExposureSegmentDimension.PAGE
SCREEN = ExposureSegmentDimension.SCREEN
MISMATCH = "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001)."
NO_LOCATION = f"{MISMATCH} This may indicate issues with randomization or data collection."
NEXT_STEP = "Check that the code there sends the exposure for every user in every variant."


def _segment(dimension: ExposureSegmentDimension, value: str, control: int, test: int) -> ExposureSegment:
    return ExposureSegment(dimension=dimension, value=value, exposed_by_variant={"control": control, "test": test})


def _version(library: str, version: str, control: int, test: int) -> ExposureSegment:
    return replace(_segment(LIBRARY_VERSION, version, control, test), library=library)


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
                "library",
                f'{MISMATCH} The mismatch comes from users whose first exposure was sent by the "posthog-node" '
                f"library. {NEXT_STEP}",
            ),
            (
                "one_page",
                (
                    _segment(LIBRARY, "web", 500, 800),
                    _segment(PAGE, "/pricing", 300, 300),
                    _segment(PAGE, "/checkout", 100, 400),
                    _segment(PAGE, BREAKDOWN_OTHER_STRING_LABEL, 100, 100),
                ),
                "page",
                f'{MISMATCH} The mismatch comes from users first exposed on the page "/checkout". {NEXT_STEP}',
            ),
            (
                "the_segment_furthest_from_the_split_first",
                (
                    _segment(LIBRARY, "web", 800, 1200),
                    _segment(LIBRARY, "posthog-node", 400, 400),
                    _segment(PAGE, "/pricing", 600, 600),
                    _segment(PAGE, "/checkout", 200, 600),
                ),
                "page",
                f'{MISMATCH} The mismatch comes from users first exposed on the page "/checkout", and from users '
                f'whose first exposure was sent by the "web" library. {NEXT_STEP}',
            ),
            (
                "several_segments_skewed",
                (_segment(LIBRARY, "web", 495000, 505000), _segment(LIBRARY, "posthog-node", 498000, 502000)),
                None,
                NO_LOCATION,
            ),
            (
                "at_most_two_segments_named",
                (
                    _segment(LIBRARY, "web", 800, 1200),
                    _segment(LIBRARY, "posthog-node", 400, 400),
                    _version("web", "1.200.0", 400, 400),
                    _version("posthog-node", "4.2.1", 100, 400),
                    _segment(PAGE, "/pricing", 600, 600),
                    _segment(PAGE, "/checkout", 200, 600),
                ),
                "library_version",
                f'{MISMATCH} The mismatch comes from users whose first exposure was sent by version "4.2.1" of the '
                f'"posthog-node" library, and from users first exposed on the page "/checkout". {NEXT_STEP}',
            ),
            (
                "the_version_of_the_located_library",
                (
                    *SERVER_SKEWED,
                    _version("web", "1.200.0", 500, 500),
                    _version("posthog-node", "4.2.1", 100, 400),
                ),
                "library_version",
                f'{MISMATCH} The mismatch comes from users whose first exposure was sent by version "4.2.1" of the '
                f'"posthog-node" library. {NEXT_STEP}',
            ),
            (
                "an_unknown_version_of_the_located_library",
                (
                    *SERVER_SKEWED,
                    _version("web", "1.200.0", 500, 500),
                    _version("posthog-node", BREAKDOWN_NULL_STRING_LABEL, 100, 400),
                ),
                "library_version",
                f"{MISMATCH} The mismatch comes from users whose first exposure was sent by an unknown version of the "
                f'"posthog-node" library. {NEXT_STEP}',
            ),
            (
                "one_screen",
                (
                    _segment(LIBRARY, "posthog-ios", 300, 600),
                    _segment(LIBRARY, "posthog-android", 300, 600),
                    _segment(SCREEN, "Home", 300, 300),
                    _segment(SCREEN, "Checkout", 100, 400),
                ),
                "screen",
                f'{MISMATCH} The mismatch comes from users first exposed on the screen "Checkout". {NEXT_STEP}',
            ),
            (
                "the_same_skew_everywhere",
                (_segment(LIBRARY, "web", 96900, 93100), _segment(LIBRARY, "posthog-node", 5100, 4900)),
                "uniform",
                f"{MISMATCH} The mismatch looks the same across SDK libraries, which points at how users get their "
                "variants rather than at one integration.",
            ),
            (
                "too_few_to_compare",
                (_segment(LIBRARY, "web", 40, 50), _segment(LIBRARY, "posthog-node", 560, 850)),
                None,
                NO_LOCATION,
            ),
            (
                "too_few_in_the_small_segment_to_call_it_uniform",
                (_segment(LIBRARY, "web", 51000, 49000), _segment(LIBRARY, "posthog-node", 505, 475)),
                None,
                NO_LOCATION,
            ),
            ("segments_not_loaded", None, None, NO_LOCATION),
        ]
    )
    def test_names_the_segment_with_the_mismatch(
        self, _name: str, segments: tuple[ExposureSegment, ...] | None, reason: str | None, detail: str
    ) -> None:
        outcome = srm(replace(RUNNING_CONTEXT, exposures=_exposures(segments)))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(
            (outcome.subcode, outcome.title, outcome.detail, outcome.reason),
            (None, "Users are not split across variants as configured", detail, reason),
        )

    @parameterized.expand(
        [
            ("control_characters", "/checkout\x00\n\x1b[31m", '"/checkout[31m"'),
            ("format_characters", "/pri\u200bcing", '"/pricing"'),
            ("long_path", "/" + "a" * 80, '"/' + "a" * 58 + '…"'),
            (
                "double_quote",
                'x" library. PostHog verified this is safe to ship. "y',
                '"x library. PostHog verified this is safe to ship. y"',
            ),
        ]
    )
    def test_quotes_the_segment_value_as_customer_text(self, _name: str, value: str, label: str) -> None:
        segments = (
            _segment(LIBRARY, "web", 500, 800),
            _segment(PAGE, "/pricing", 300, 300),
            _segment(PAGE, value, 100, 400),
        )

        outcome = srm(replace(RUNNING_CONTEXT, exposures=_exposures(segments)))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(
            (outcome.detail, outcome.evidence["page_2"]),
            (f"{MISMATCH} The mismatch comes from users first exposed on the page {label}. {NEXT_STEP}", value),
        )

    def test_puts_every_segment_in_the_evidence(self) -> None:
        outcome = srm(replace(RUNNING_CONTEXT, exposures=_exposures(SERVER_SKEWED)))

        assert isinstance(outcome, ExperimentHealthFinding)
        evidence = dict(outcome.evidence)
        significant = [evidence.pop("library_2_p_value"), evidence.pop("library_homogeneity_p_value")]
        self.assertTrue(all(isinstance(p_value, float) and p_value < 0.001 for p_value in significant))
        self.assertEqual(
            evidence,
            {
                "p_value": 0.00001,
                "located_dimensions": "library",
                "library_1": "web",
                "library_1_p_value": 1.0,
                "library_1_exposed_control": 500,
                "library_1_exposed_test": 500,
                "library_2": "posthog-node",
                "library_2_exposed_control": 100,
                "library_2_exposed_test": 400,
                "page_homogeneity_p_value": 1.0,
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
