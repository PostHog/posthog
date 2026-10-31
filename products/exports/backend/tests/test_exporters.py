from collections.abc import Mapping

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.exports.backend.facade import exporters


def _content_path(*, team_id: int, asset_id: int, export_context: Mapping[str, object]) -> str:
    return f"/api/projects/{team_id}/owner/{asset_id}/content"


class TestExportFormatHandlers(SimpleTestCase):
    def setUp(self) -> None:
        registry_patch = patch.dict(exporters._export_format_handlers, clear=True)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)

    def _register(self, handler: MagicMock) -> None:
        exporters.register_export_format_handler(
            export_format="application/json", kind="test_kind", handler=handler, content_path=_content_path
        )

    @parameterized.expand(
        [
            ("the registered pair", "application/json", "test_kind", True),
            ("the same kind in another format", "application/x-ndjson", "test_kind", False),
            ("another kind", "application/json", "other_kind", False),
            ("no kind", "application/json", None, False),
        ]
    )
    def test_finds_a_handler_by_format_and_kind(
        self, _name: str, export_format: str, kind: str | None, found: bool
    ) -> None:
        handler = MagicMock()
        self._register(handler)

        assert (exporters.get_export_format_handler(export_format=export_format, kind=kind) is handler) == found

    def test_registering_the_same_handler_again_is_allowed_but_a_different_one_is_refused(self) -> None:
        handler = MagicMock()
        self._register(handler)
        self._register(handler)

        with self.assertRaises(ValueError):
            self._register(MagicMock())
