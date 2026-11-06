from dataclasses import replace

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.srm import reads_segments, srm
from products.experiments.backend.health.context import ExposureSegment, ExposureTotals, parse_flag_state
from products.experiments.backend.health.skips import CheckSkip
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
        filters_test_accounts=False,
        has_positive_test_account_filter=False,
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
                "share_off_split": 0.1,
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


EVEN_SPLIT = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
EVERYONE = {"properties": [], "rollout_percentage": 100}


PINNED_TEST = (
    f'{MISMATCH} Set 1 sets the variant override "test", so the users it matches get "test" instead of a variant from '
    "the split, which can cause this. If these are internal or test users, check that the filter for internal and test "
    "users excludes them from the results. Otherwise remove the override."
)


def _pinned_to(variant: str) -> dict[str, object]:
    return {
        "properties": [{"key": "$geoip_country_code", "value": ["DE"], "operator": "exact", "type": "person"}],
        "rollout_percentage": 100,
        "variant": variant,
    }


class TestSrmCauses(TestCase):
    @parameterized.expand(
        [
            (
                "half_a_percent_off",
                {"control": 50500, "test": 49500},
                {"control": 50000, "test": 50000},
                ExperimentHealthFindingSeverity.INFO,
                f"{MISMATCH} Only 0.5% of users would have to switch variants to match the split, so the difference "
                "is unlikely to change the results. This may indicate issues with randomization or data collection.",
            ),
            (
                "three_variants_under_one_percent_off",
                {"control": 33200, "test": 33300, "blue": 33500},
                {"control": 34000, "test": 33000, "blue": 33000},
                ExperimentHealthFindingSeverity.INFO,
                f"{MISMATCH} Only 0.8% of users would have to switch variants to match the split, so the difference "
                "is unlikely to change the results. This may indicate issues with randomization or data collection.",
            ),
            (
                "just_under_one_percent_off",
                {"control": 50990, "test": 49010},
                {"control": 50000, "test": 50000},
                ExperimentHealthFindingSeverity.INFO,
                f"{MISMATCH} Only 0.9% of users would have to switch variants to match the split, so the difference "
                "is unlikely to change the results. This may indicate issues with randomization or data collection.",
            ),
            (
                "under_a_tenth_of_a_percent_off",
                {"control": 5002000, "test": 4998000},
                {"control": 5000000, "test": 5000000},
                ExperimentHealthFindingSeverity.INFO,
                f"{MISMATCH} Fewer than 0.1% of users would have to switch variants to match the split, so the "
                "difference is unlikely to change the results. This may indicate issues with randomization or data "
                "collection.",
            ),
            (
                "one_percent_off",
                {"control": 51000, "test": 49000},
                {"control": 50000, "test": 50000},
                ExperimentHealthFindingSeverity.WARNING,
                NO_LOCATION,
            ),
        ]
    )
    def test_a_mismatch_of_under_one_percent_of_users_is_info(
        self,
        _name: str,
        total_exposures: dict[str, int],
        expected: dict[str, float],
        severity: ExperimentHealthFindingSeverity,
        detail: str,
    ) -> None:
        exposures = replace(_exposures(None), total_exposures=total_exposures, sample_ratio_expected=expected)

        outcome = srm(replace(RUNNING_CONTEXT, exposures=exposures))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual((outcome.severity, outcome.detail), (severity, detail))

    @parameterized.expand(
        [
            (
                "override_of_the_variant_in_excess",
                [_pinned_to("test"), EVERYONE],
                False,
                None,
                ("some_conditions_pinned", True),
                PINNED_TEST,
            ),
            (
                "override_and_a_uniform_mismatch",
                [_pinned_to("test"), EVERYONE],
                False,
                (_segment(LIBRARY, "web", 400, 600), _segment(LIBRARY, "posthog-node", 400, 600)),
                ("some_conditions_pinned", True),
                PINNED_TEST,
            ),
            (
                "override_and_a_segment_with_the_mismatch",
                [_pinned_to("test"), EVERYONE],
                False,
                SERVER_SKEWED,
                (None, True),
                f'{MISMATCH} The mismatch comes from users whose first exposure was sent by the "posthog-node" '
                f"library. {NEXT_STEP}",
            ),
            (
                "override_of_the_other_variant",
                [_pinned_to("control"), EVERYONE],
                False,
                None,
                (None, True),
                NO_LOCATION,
            ),
            ("override_after_the_end", [_pinned_to("test"), EVERYONE], True, None, (None, True), NO_LOCATION),
            (
                "every_condition_overridden_after_the_end",
                [_pinned_to("test"), {**EVERYONE, "variant": "control"}],
                True,
                None,
                (None, True),
                NO_LOCATION,
            ),
        ]
    )
    def test_names_a_variant_override_of_the_variant_in_excess(
        self,
        _name: str,
        groups: list[dict[str, object]],
        has_ended: bool,
        segments: tuple[ExposureSegment, ...] | None,
        expected: tuple[str | None, bool],
        detail: str,
    ) -> None:
        ctx = replace(
            RUNNING_CONTEXT,
            has_ended=has_ended,
            flag=parse_flag_state(active=True, deleted=False, groups=groups, variants=EVEN_SPLIT),
            exposures=_exposures(segments),
        )

        outcome = srm(ctx)

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(((outcome.subcode, reads_segments(ctx)), outcome.detail), (expected, detail))

    def test_leaves_a_split_that_assigns_nobody_to_the_variant_override_finding(self) -> None:
        ctx = replace(
            RUNNING_CONTEXT,
            flag=parse_flag_state(
                active=True,
                deleted=False,
                groups=[_pinned_to("test"), {**EVERYONE, "variant": "control"}],
                variants=EVEN_SPLIT,
            ),
            exposures=_exposures(None),
        )

        outcome = srm(ctx)

        assert isinstance(outcome, CheckSkip)
        self.assertEqual(
            outcome.reason, "The split assigns nobody, because every release condition sets a variant override"
        )
