"""Pure-function tests for per-story threshold overrides.

The classification math and stem derivation carry the whole feature: if the stem
strips the wrong tokens, an override never matches the story it was set for; if
`effective_thresholds` / `classify_compare_result` ignore the override, the story
keeps flagging. These are pure so they stay at the bottom of the test pyramid.
"""

from parameterized import parameterized

from products.visual_review.backend.diff import CompareResult
from products.visual_review.backend.diffing import classify_compare_result
from products.visual_review.backend.facade.enums import ChangeKind
from products.visual_review.backend.identifiers import story_stem
from products.visual_review.backend.models import StoryThresholdOverride
from products.visual_review.backend.thresholds import (
    PIXEL_DIFF_THRESHOLD_PERCENT,
    SSIM_DISSIMILARITY_THRESHOLD,
    effective_thresholds,
)


def _result(diff_percentage: float, ssim_score: float) -> CompareResult:
    return CompareResult(
        diff_image=None,
        diff_hash="",
        diff_percentage=diff_percentage,
        diff_pixel_count=0,
        ssim_score=ssim_score,
        width=100,
        height=100,
        thumbnail=None,
        thumbnail_hash="",
        size_mismatch=False,
        cluster_summary=None,
    )


class TestStoryStem:
    @parameterized.expand(
        [
            ("theme only", "scenes-app-dashboards--edit--light", "scenes-app-dashboards--edit"),
            ("theme dark", "scenes-app-dashboards--edit--dark", "scenes-app-dashboards--edit"),
            ("width + theme", "scenes-app-dashboards--edit--wide--light", "scenes-app-dashboards--edit"),
            ("theme + browser", "scenes-app-dashboards--edit--light--webkit", "scenes-app-dashboards--edit"),
            (
                "width + theme + browser",
                "scenes-app-dashboards--edit--superwide--dark--webkit",
                "scenes-app-dashboards--edit",
            ),
            ("no facet tokens", "components-lemon-button", "components-lemon-button"),
            ("story word matches a token stays", "components-narrow-card--light", "components-narrow-card"),
        ]
    )
    def test_strips_to_story_stem(self, _name: str, identifier: str, expected: str) -> None:
        assert story_stem(identifier) == expected

    def test_all_variants_of_a_story_share_a_stem(self) -> None:
        stems = {
            story_stem(i)
            for i in [
                "scenes-app-dashboards--edit--light",
                "scenes-app-dashboards--edit--dark",
                "scenes-app-dashboards--edit--wide--light",
                "scenes-app-dashboards--edit--light--webkit",
            ]
        }
        assert stems == {"scenes-app-dashboards--edit"}


class TestEffectiveThresholds:
    def test_no_override_uses_global_defaults(self) -> None:
        pixel, ssim, pixel_overridden, ssim_overridden = effective_thresholds("story--light", {})
        assert (pixel, ssim) == (PIXEL_DIFF_THRESHOLD_PERCENT, SSIM_DISSIMILARITY_THRESHOLD)
        assert not pixel_overridden
        assert not ssim_overridden

    @parameterized.expand(
        [
            ("pixel only", 5.0, None, 5.0, SSIM_DISSIMILARITY_THRESHOLD, True, False),
            ("ssim only", None, 0.05, PIXEL_DIFF_THRESHOLD_PERCENT, 0.05, False, True),
            ("both", 5.0, 0.05, 5.0, 0.05, True, True),
        ]
    )
    def test_override_tiers_are_independent(
        self,
        _name: str,
        pixel_col: float | None,
        ssim_col: float | None,
        want_pixel: float,
        want_ssim: float,
        want_pixel_overridden: bool,
        want_ssim_overridden: bool,
    ) -> None:
        override = StoryThresholdOverride(
            story_stem="scenes-app-dashboards--edit",
            pixel_threshold_percent=pixel_col,
            ssim_dissimilarity_threshold=ssim_col,
        )
        overrides = {override.story_stem: override}

        # An identifier from the story (with facet tokens) must resolve via its stem.
        pixel, ssim, pixel_overridden, ssim_overridden = effective_thresholds(
            "scenes-app-dashboards--edit--wide--dark--webkit", overrides
        )
        assert pixel == want_pixel
        assert ssim == want_ssim
        assert pixel_overridden is want_pixel_overridden
        assert ssim_overridden is want_ssim_overridden


class TestClassificationRespectsOverrides:
    def test_structural_movement_below_override_stops_flagging(self) -> None:
        # 0.28% pixels (under the 2.5% pixel tier) but 1.5% structural — trips the
        # default 1% SSIM tier. This is the flaky-movement case the feature fixes.
        result = _result(diff_percentage=0.28, ssim_score=0.985)

        assert classify_compare_result(result) == ChangeKind.STRUCTURAL

        override = StoryThresholdOverride(
            story_stem="scenes-app-dashboards--edit",
            pixel_threshold_percent=None,
            ssim_dissimilarity_threshold=0.02,  # allow up to 2% structural
        )
        overrides = {override.story_stem: override}
        pixel, ssim, _, _ = effective_thresholds("scenes-app-dashboards--edit--light", overrides)
        assert classify_compare_result(result, pixel, ssim) is None

    def test_override_does_not_mask_a_genuine_pixel_change(self) -> None:
        # Relaxing structural must not let a real pixel-tier change through.
        result = _result(diff_percentage=8.0, ssim_score=0.90)
        override = StoryThresholdOverride(
            story_stem="scenes-app-dashboards--edit",
            pixel_threshold_percent=None,
            ssim_dissimilarity_threshold=0.5,
        )
        overrides = {override.story_stem: override}
        pixel, ssim, _, _ = effective_thresholds("scenes-app-dashboards--edit--light", overrides)
        assert classify_compare_result(result, pixel, ssim) == ChangeKind.PIXEL

    @parameterized.expand(
        [
            ("under custom pixel threshold", 4.0, 1.0, 5.0, 0.01, None),
            ("at custom pixel threshold", 5.0, 1.0, 5.0, 0.01, ChangeKind.PIXEL),
        ]
    )
    def test_custom_pixel_threshold(
        self,
        _name: str,
        diff_percentage: float,
        ssim_score: float,
        pixel_threshold: float,
        ssim_threshold: float,
        expected: ChangeKind | None,
    ) -> None:
        result = _result(diff_percentage=diff_percentage, ssim_score=ssim_score)
        assert classify_compare_result(result, pixel_threshold, ssim_threshold) == expected
