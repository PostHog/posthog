from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource


class TestLangfuseSource:
    def setup_method(self):
        self.source = LangfuseSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.host = "https://cloud.langfuse.com"
        self.config.public_key = "pk-lf-key"
        self.config.secret_key = "sk-lf-key"

    def test_v1_is_deprecated_advisory_and_default_is_v2(self):
        # New sources start on v2; v1 stays supported so already-pinned rows keep resolving to the
        # unchanged wire. Langfuse announced no sunset date, so the deprecation is advisory
        # (sunset_at is None) — the generic in-product warning fires but no repin migration ships.
        assert self.source.default_version == "v2"
        assert set(self.source.supported_versions) == {"v1", "v2"}

        deprecation = self.source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert self.source.get_version_deprecation("v2") is None
