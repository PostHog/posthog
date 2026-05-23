"""Verify the facade returns frozen dataclasses (never ORM objects)."""

import dataclasses
from unittest.mock import patch

import pytest

from products.social_signals.backend.facade import api, contracts
from products.social_signals.backend.facade.contracts import (
    CreateMentionInput,
    MentionFilters,
)
from products.social_signals.backend.facade.enums import (
    MentionType,
    Platform,
    SourceKind,
)
from products.social_signals.backend.models import Mention, MentionSource

PRODUCT_DATABASES = {"default", "social_signals_db_writer", "social_signals_db_reader"}


@pytest.fixture
def source(team):
    return MentionSource.objects.create(team_id=team.id, kind=SourceKind.OCTOLENS.value)


@pytest.mark.django_db(databases=PRODUCT_DATABASES, transaction=True)
class TestFacadeReturnsDataclasses:
    def test_list_sources_returns_contracts(self, team, source):
        result = api.list_sources(team.id)
        assert len(result) == 1
        assert isinstance(result[0], contracts.MentionSource)
        assert dataclasses.is_dataclass(result[0])

    def test_get_or_create_source_idempotent(self, team):
        a = api.get_or_create_source(team_id=team.id, kind=SourceKind.OCTOLENS.value)
        b = api.get_or_create_source(team_id=team.id, kind=SourceKind.OCTOLENS.value)
        assert a.id == b.id

    def test_rotate_token_changes_value(self, team, source):
        before = api.get_source(team_id=team.id, source_id=source.id).ingest_token
        rotated = api.rotate_source_token(team_id=team.id, source_id=source.id)
        assert rotated.ingest_token != before

    def test_list_mentions_returns_contracts(self, team, source):
        Mention.objects.create(
            team_id=team.id,
            source=source,
            external_id="m1",
            platform=Platform.X.value,
            mention_type=MentionType.POST.value,
            content="hello",
        )
        result = api.list_mentions(team_id=team.id, filters=MentionFilters())
        assert len(result) == 1
        assert isinstance(result[0], contracts.Mention)
        assert result[0].content == "hello"

    def test_ingest_from_webhook_smoke(self, team, source):
        payload = {"id": "ingest-1", "platform": "x", "content": "Hi"}
        with patch(
            "products.social_signals.backend.tasks.tasks.analyze_mention_task.delay"
        ):
            result = api.ingest_from_webhook(
                ingest_token=source.ingest_token, payload=payload
            )
        assert isinstance(result, contracts.IngestResult)
        assert result.accepted == 1
        assert result.skipped == 0

    def test_ingest_from_webhook_unknown_token(self, team):
        with pytest.raises(api.MentionSourceNotFoundError):
            api.ingest_from_webhook(ingest_token="nope", payload={})

    def test_ingest_mention_returns_mention_with_analyses(self, team, source):
        with patch(
            "products.social_signals.backend.tasks.tasks.analyze_mention_task.delay"
        ):
            mention = api.ingest_mention(
                CreateMentionInput(
                    team_id=team.id,
                    source_id=source.id,
                    platform=Platform.X.value,
                    mention_type=MentionType.POST.value,
                    external_id="direct-1",
                )
            )
        assert isinstance(mention, contracts.Mention)
        assert mention.external_id == "direct-1"
        # Analyses list is present (empty at this point)
        assert mention.analyses == []
