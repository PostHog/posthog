from unittest.mock import patch

import pytest

from products.social_signals.backend.facade.enums import (
    MentionType,
    Platform,
    ProcessingStatus,
    SourceKind,
)
from products.social_signals.backend.models import Mention, MentionSource
from products.social_signals.backend.tasks.tasks import analyze_mention_task

PRODUCT_DATABASES = {"default", "social_signals_db_writer", "social_signals_db_reader"}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_analyze_mention_task_marks_done(team):
    source = MentionSource.objects.create(team_id=team.id, kind=SourceKind.OCTOLENS.value)
    mention = Mention.objects.create(
        team_id=team.id,
        source=source,
        external_id="task-1",
        platform=Platform.X.value,
        mention_type=MentionType.POST.value,
        content="Quick test",
    )

    fake = {
        "sentiment": "neutral",
        "sentiment_score": 0.0,
        "category": "other",
        "summary": "ok",
        "is_actionable": False,
    }

    with patch(
        "products.social_signals.backend.analyzers.classify_and_sentiment.ClassifyAndSentimentAnalyzer.run",
        return_value=fake,
    ):
        analyze_mention_task(mention_id=str(mention.id))

    mention.refresh_from_db()
    assert mention.status == ProcessingStatus.DONE.value
    assert mention.analyses.count() == 1
