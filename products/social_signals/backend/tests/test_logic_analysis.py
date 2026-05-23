from unittest.mock import patch

import pytest

from products.social_signals.backend.analyzers.classify_and_sentiment import (
    ClassifyAndSentimentAnalyzer,
)
from products.social_signals.backend.facade.enums import (
    AnalysisStatus,
    AnalyzerKind,
    MentionType,
    Platform,
    ProcessingStatus,
    SourceKind,
)
from products.social_signals.backend.logic.analysis import run_analyzers_for_mention
from products.social_signals.backend.models import (
    Mention,
    MentionAnalysis,
    MentionSource,
)

PRODUCT_DATABASES = {"default", "social_signals_db_writer", "social_signals_db_reader"}


@pytest.fixture
def mention(team):
    source = MentionSource.objects.create(team_id=team.id, kind=SourceKind.OCTOLENS.value)
    return Mention.objects.create(
        team_id=team.id,
        source=source,
        external_id="a1",
        platform=Platform.X.value,
        mention_type=MentionType.POST.value,
        content="The new dashboards are great.",
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunAnalyzersForMention:
    def test_writes_succeeded_row_and_done_status(self, team, mention):
        fake_result = {
            "sentiment": "positive",
            "sentiment_score": 0.7,
            "category": "praise",
            "summary": "praise of dashboards",
            "is_actionable": False,
        }
        with patch.object(ClassifyAndSentimentAnalyzer, "run", return_value=fake_result):
            run_analyzers_for_mention(str(mention.id))

        mention.refresh_from_db()
        assert mention.status == ProcessingStatus.DONE.value

        analysis = MentionAnalysis.objects.get(
            mention=mention, kind=AnalyzerKind.CLASSIFY_AND_SENTIMENT.value
        )
        assert analysis.status == AnalysisStatus.SUCCEEDED.value
        assert analysis.result["sentiment"] == "positive"
        assert analysis.error == ""

    def test_failed_analyzer_marks_failure_and_keeps_others(self, team, mention):
        with patch.object(ClassifyAndSentimentAnalyzer, "run", side_effect=RuntimeError("LLM down")):
            run_analyzers_for_mention(str(mention.id))

        mention.refresh_from_db()
        assert mention.status == ProcessingStatus.FAILED.value

        analysis = MentionAnalysis.objects.get(mention=mention)
        assert analysis.status == AnalysisStatus.FAILED.value
        assert "LLM down" in analysis.error

    def test_rerun_overwrites_existing_row(self, team, mention):
        first = {
            "sentiment": "negative",
            "sentiment_score": -0.4,
            "category": "complaint",
            "summary": "v1",
            "is_actionable": True,
        }
        second = {
            "sentiment": "neutral",
            "sentiment_score": 0.0,
            "category": "question",
            "summary": "v2",
            "is_actionable": False,
        }
        with patch.object(ClassifyAndSentimentAnalyzer, "run", return_value=first):
            run_analyzers_for_mention(str(mention.id))
        with patch.object(ClassifyAndSentimentAnalyzer, "run", return_value=second):
            run_analyzers_for_mention(str(mention.id))

        rows = list(MentionAnalysis.objects.filter(mention=mention))
        assert len(rows) == 1
        assert rows[0].result["summary"] == "v2"

    def test_missing_mention_is_noop(self):
        import uuid

        # Should not raise even though no mention exists
        run_analyzers_for_mention(str(uuid.uuid4()))
