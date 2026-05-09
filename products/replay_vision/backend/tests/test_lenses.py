from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses import LENS_REGISTRY, get_lens_impl
from products.replay_vision.backend.temporal.lenses.classifier import ClassifierSegmentOutput
from products.replay_vision.backend.temporal.lenses.indexer import IndexerOutput, IndexerSegmentOutput
from products.replay_vision.backend.temporal.lenses.monitor import MonitorSegmentOutput
from products.replay_vision.backend.temporal.lenses.scorer import ScorerSegmentOutput
from products.replay_vision.backend.temporal.lenses.summarizer import SummarizerOutput, SummarizerSegmentOutput

VISION_TEST = "products.replay_vision.backend.temporal.lenses"


class TestLensRegistry(BaseTest):
    def test_all_lens_types_registered(self) -> None:
        self.assertEqual(set(LENS_REGISTRY.keys()), set(LensType))

    @parameterized.expand([(t.value,) for t in LensType])
    def test_get_lens_impl_by_value(self, value: str) -> None:
        impl = get_lens_impl(value)
        self.assertEqual(impl.lens_type.value, value)


class TestLensSchemas(BaseTest):
    @parameterized.expand([(t,) for t in LensType])
    def test_segment_output_has_confidence(self, lens_type: LensType) -> None:
        impl = get_lens_impl(lens_type)
        self.assertIn("confidence", impl.SegmentOutput.model_fields)

    @parameterized.expand([(t,) for t in LensType])
    def test_final_output_has_confidence(self, lens_type: LensType) -> None:
        impl = get_lens_impl(lens_type)
        self.assertIn("confidence", impl.FinalOutput.model_fields)


class TestMonitorConsolidate(BaseTest):
    async def test_any_true_segment_makes_verdict_true(self) -> None:
        impl = get_lens_impl(LensType.MONITOR)
        segments = [
            MonitorSegmentOutput(verdict=False, reasoning="r0", confidence=0.9),
            MonitorSegmentOutput(verdict=True, reasoning="r1", confidence=0.7),
        ]
        result = await impl.consolidate(segments, {"prompt": "p"})
        self.assertTrue(result.verdict)
        # Verdicts disagree → confidence is min.
        self.assertEqual(result.confidence, 0.7)

    async def test_all_false_makes_verdict_false_avg_confidence(self) -> None:
        impl = get_lens_impl(LensType.MONITOR)
        segments = [
            MonitorSegmentOutput(verdict=False, reasoning="r0", confidence=0.8),
            MonitorSegmentOutput(verdict=False, reasoning="r1", confidence=0.6),
        ]
        result = await impl.consolidate(segments, {"prompt": "p"})
        self.assertFalse(result.verdict)
        self.assertAlmostEqual(result.confidence, 0.7)

    async def test_empty_segments_returns_zero_confidence(self) -> None:
        impl = get_lens_impl(LensType.MONITOR)
        result = await impl.consolidate([], {"prompt": "p"})
        self.assertFalse(result.verdict)
        self.assertEqual(result.confidence, 0.0)


class TestClassifierConsolidate(BaseTest):
    async def test_tags_unioned_and_filtered_to_allowed(self) -> None:
        impl = get_lens_impl(LensType.CLASSIFIER)
        segments = [
            ClassifierSegmentOutput(tags=["a", "b"], reasoning="r0", confidence=0.8),
            ClassifierSegmentOutput(tags=["b", "c", "rogue"], reasoning="r1", confidence=0.6),
        ]
        result = await impl.consolidate(segments, {"prompt": "p", "tags": ["a", "b", "c"]})
        self.assertEqual(result.tags, ["a", "b", "c"])
        self.assertAlmostEqual(result.confidence, 0.7)


class TestScorerConsolidate(BaseTest):
    async def test_score_averaged_label_echoed(self) -> None:
        impl = get_lens_impl(LensType.SCORER)
        segments = [
            ScorerSegmentOutput(score=0.8, reasoning="r0", confidence=1.0),
            ScorerSegmentOutput(score=0.4, reasoning="r1", confidence=0.5),
        ]
        result = await impl.consolidate(segments, {"prompt": "p", "scale": {"min": 0, "max": 1, "label": "engagement"}})
        self.assertAlmostEqual(result.score, 0.6)
        self.assertEqual(result.label, "engagement")
        self.assertAlmostEqual(result.confidence, 0.75)


class TestSummarizerConsolidate(BaseTest):
    async def test_consolidate_calls_gemini_with_consolidate_prompt(self) -> None:
        impl = get_lens_impl(LensType.SUMMARIZER)
        segments = [
            SummarizerSegmentOutput(title="T0", summary="S0", confidence=0.8),
            SummarizerSegmentOutput(title="T1", summary="S1", confidence=0.7),
        ]
        mock_response = AsyncMock(text='{"title": "Final", "summary": "Final summary", "confidence": 0.85}')
        mock_client = AsyncMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)
        with patch(f"{VISION_TEST}.summarizer.genai.AsyncClient", return_value=mock_client):
            result = await impl.consolidate(segments, {"prompt": "p", "length": "short"})
        self.assertEqual(result.title, "Final")
        self.assertEqual(result.summary, "Final summary")
        self.assertEqual(result.confidence, 0.85)
        self.assertIsInstance(result, SummarizerOutput)

    async def test_empty_segments_returns_placeholder(self) -> None:
        impl = get_lens_impl(LensType.SUMMARIZER)
        result = await impl.consolidate([], {"prompt": "p"})
        self.assertEqual(result.confidence, 0.0)


class TestIndexerConsolidate(BaseTest):
    async def test_consolidate_calls_gemini(self) -> None:
        impl = get_lens_impl(LensType.INDEXER)
        segments = [
            IndexerSegmentOutput(
                summary="S0", user_type="returning", outcome="bought", keywords=["checkout"], confidence=0.9
            ),
        ]
        mock_response = AsyncMock(
            text='{"summary": "Final", "user_type": "returning", "outcome": "bought", '
            '"keywords": ["checkout", "purchase"], "confidence": 0.9}'
        )
        mock_client = AsyncMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)
        with patch(f"{VISION_TEST}.indexer.genai.AsyncClient", return_value=mock_client):
            result = await impl.consolidate(segments, {"prompt": "p"})
        self.assertEqual(result.summary, "Final")
        self.assertEqual(result.keywords, ["checkout", "purchase"])
        self.assertIsInstance(result, IndexerOutput)
