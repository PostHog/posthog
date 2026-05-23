import json
from pathlib import Path

import pytest

from products.social_signals.backend.facade.enums import Platform, SourceKind
from products.social_signals.backend.logic.adapters import get_adapter
from products.social_signals.backend.logic.adapters.octolens import OctolensAdapter
from products.social_signals.backend.models import MentionSource

PRODUCT_DATABASES = {"default", "social_signals_db_writer", "social_signals_db_reader"}

FIXTURE = Path(__file__).parent / "fixtures" / "octolens_webhook.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestOctolensAdapter:
    @pytest.fixture
    def source(self, team):
        return MentionSource.objects.create(team_id=team.id, kind=SourceKind.OCTOLENS.value)

    def test_registry_returns_instance(self):
        adapter = get_adapter(SourceKind.OCTOLENS.value)
        assert isinstance(adapter, OctolensAdapter)

    def test_unknown_kind_raises(self):
        from products.social_signals.backend.logic.errors import UnknownAdapterError

        with pytest.raises(UnknownAdapterError):
            get_adapter("not_a_real_source")

    def test_envelope_with_mentions_array(self, source):
        adapter = OctolensAdapter()
        inputs = adapter.to_create_inputs(_load_fixture(), source)
        assert len(inputs) == 2
        ids = {i.external_id for i in inputs}
        assert ids == {"octolens-mention-1", "octolens-mention-2"}

    def test_platform_normalization(self, source):
        adapter = OctolensAdapter()
        inputs = adapter.to_create_inputs(_load_fixture(), source)
        platforms = {i.external_id: i.platform for i in inputs}
        assert platforms["octolens-mention-1"] == Platform.X.value  # "twitter" → x
        assert platforms["octolens-mention-2"] == Platform.REDDIT.value

    def test_single_root_object(self, source):
        adapter = OctolensAdapter()
        payload = {
            "id": "solo-1",
            "platform": "hackernews",
            "url": "https://news.ycombinator.com/item?id=1",
            "body": "Plain HN payload",
            "created_at": "2026-05-01T00:00:00Z",
        }
        inputs = adapter.to_create_inputs(payload, source)
        assert len(inputs) == 1
        assert inputs[0].external_id == "solo-1"
        assert inputs[0].platform == Platform.HACKER_NEWS.value
        assert inputs[0].content == "Plain HN payload"

    def test_missing_id_is_dropped(self, source):
        adapter = OctolensAdapter()
        inputs = adapter.to_create_inputs({"mentions": [{"platform": "x", "content": "no id"}]}, source)
        assert inputs == []

    def test_unknown_platform_falls_back_to_other(self, source):
        adapter = OctolensAdapter()
        inputs = adapter.to_create_inputs(
            {"mentions": [{"id": "u1", "platform": "tiktok", "content": "Hi"}]},
            source,
        )
        assert len(inputs) == 1
        assert inputs[0].platform == Platform.OTHER.value

    def test_flat_author_fields(self, source):
        adapter = OctolensAdapter()
        inputs = adapter.to_create_inputs(
            {
                "mentions": [
                    {
                        "id": "flat-1",
                        "platform": "x",
                        "author_username": "jane",
                        "author_name": "Jane Dev",
                        "author_url": "https://x.com/jane",
                        "author_followers": "1234",
                    }
                ]
            },
            source,
        )
        assert inputs[0].author_handle == "jane"
        assert inputs[0].author_display_name == "Jane Dev"
        assert inputs[0].author_followers == 1234

    def test_nonsense_payload_returns_empty(self, source):
        adapter = OctolensAdapter()
        # {"unrelated": "data"} → fallthrough to single-root-object → no
        # external_id → dropped by _to_input
        assert adapter.to_create_inputs({"unrelated": "data"}, source) == []
        assert adapter.to_create_inputs([], source) == []
