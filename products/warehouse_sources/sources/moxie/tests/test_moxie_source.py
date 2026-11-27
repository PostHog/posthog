import pytest

from products.warehouse_sources.sources.moxie._config import MoxieSourceConfig
from products.warehouse_sources.sources.moxie.canonical_descriptions import CANONICAL_DESCRIPTIONS
from products.warehouse_sources.sources.moxie.settings import ENDPOINTS
from products.warehouse_sources.sources.moxie.source import MoxieSource


class TestMoxieSource:
    def setup_method(self) -> None:
        self.source = MoxieSource()
        self.team_id = 123
        self.config = MoxieSourceConfig(base_url="https://pod00.withmoxie.dev/api/public", api_key="test_key")

    def test_connection_host_fields(self) -> None:
        # base_url carries the API key's destination, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["base_url"]

    def test_canonical_descriptions_keyed_by_endpoint_names(self) -> None:
        # A renamed endpoint would silently orphan its curated descriptions.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "schema_name, expected",
        [
            ("ticket_comments", True),
            ("project_notes", True),
            ("tickets", False),
            ("time_entries", False),
            ("unknown", False),
            (None, False),
        ],
    )
    def test_resume_covers_only_the_fan_out_tables(self, schema_name: str | None, expected: bool) -> None:
        # Tables that save no resume state must keep the ordinary retry budget.
        assert self.source.resume_covers_run(incremental_or_append=False, schema_name=schema_name) is expected
