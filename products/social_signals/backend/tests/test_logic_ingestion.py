from unittest.mock import patch

import pytest

from products.social_signals.backend.facade.contracts import CreateMentionInput
from products.social_signals.backend.facade.enums import (
    MentionType,
    Platform,
    SourceKind,
)
from products.social_signals.backend.logic import ingestion
from products.social_signals.backend.logic.errors import MentionSourceNotFoundError
from products.social_signals.backend.models import Mention, MentionSource

PRODUCT_DATABASES = {"default", "social_signals_db_writer", "social_signals_db_reader"}


@pytest.fixture
def source(team):
    return MentionSource.objects.create(team_id=team.id, kind=SourceKind.OCTOLENS.value)


def _make_input(team_id: int, source_id, *, external_id: str = "ext-1", content: str = "Hello") -> CreateMentionInput:
    return CreateMentionInput(
        team_id=team_id,
        source_id=source_id,
        platform=Platform.X.value,
        mention_type=MentionType.POST.value,
        external_id=external_id,
        content=content,
    )


@pytest.mark.django_db(databases=PRODUCT_DATABASES, transaction=True)
class TestIngestBatch:
    def test_creates_and_dispatches_once(self, team, source):
        inp = _make_input(team.id, source.id)
        with patch(
            "products.social_signals.backend.tasks.tasks.analyze_mention_task.delay"
        ) as mock_delay:
            accepted, skipped = ingestion.ingest_batch([inp])

        assert (accepted, skipped) == (1, 0)
        assert Mention.objects.filter(external_id="ext-1").count() == 1
        # transaction.on_commit fires synchronously in transaction=True tests
        # once the test transaction commits — we assert exactly one dispatch.
        assert mock_delay.call_count == 1

    def test_replay_is_dedup(self, team, source):
        first = _make_input(team.id, source.id, content="v1")
        second = _make_input(team.id, source.id, content="v2-updated")

        with patch(
            "products.social_signals.backend.tasks.tasks.analyze_mention_task.delay"
        ) as mock_delay:
            ingestion.ingest_batch([first])
            ingestion.ingest_batch([second])

        # Same external_id → still one row, updated content, dispatched once
        rows = list(Mention.objects.filter(external_id="ext-1"))
        assert len(rows) == 1
        assert rows[0].content == "v2-updated"
        assert mock_delay.call_count == 1


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestSourceLookup:
    def test_by_token_returns_enabled(self, team, source):
        assert ingestion.get_source_by_token(source.ingest_token).id == source.id

    def test_by_token_skips_disabled(self, team, source):
        source.enabled = False
        source.save(update_fields=["enabled"])
        with pytest.raises(MentionSourceNotFoundError):
            ingestion.get_source_by_token(source.ingest_token)

    def test_by_token_unknown(self, team):
        with pytest.raises(MentionSourceNotFoundError):
            ingestion.get_source_by_token("not-a-real-token")
