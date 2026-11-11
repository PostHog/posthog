from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.exports.backend.models.exported_asset import ExportedAsset

DATASET_EXPORT_KIND = "dataset"

ExportFormatHandler = Callable[["ExportedAsset"], None]


class ExportContentPath(Protocol):
    def __call__(self, *, team_id: int, asset_id: int, export_context: Mapping[str, object]) -> str | None: ...


@frozen
class _Registration:
    handler: ExportFormatHandler
    content_path: ExportContentPath


_export_format_handlers: dict[tuple[str, str], _Registration] = {}


def register_export_format_handler(
    *, export_format: str, kind: str, handler: ExportFormatHandler, content_path: ExportContentPath
) -> None:
    """Route exports of this format and `export_context.kind` to a product's handler.

    The product owns the export end to end: the generic exports API returns 404 when asked for it and
    redirects its content requests, query string included, to `content_path`, an endpoint the product
    authorizes. It still lists the export for its creator.
    """
    registration = _Registration(handler=handler, content_path=content_path)
    existing = _export_format_handlers.get((export_format, kind))
    if existing is not None and existing != registration:
        raise ValueError(f"An export handler is already registered for {export_format} exports of kind {kind}.")
    _export_format_handlers[(export_format, kind)] = registration


def get_export_format_handler(*, export_format: str, kind: str | None) -> ExportFormatHandler | None:
    registration = _registration(export_format, kind)
    return registration.handler if registration is not None else None


def is_product_export(*, export_format: str, kind: str | None) -> bool:
    return _registration(export_format, kind) is not None


def get_export_content_path(
    *, export_format: str, kind: str | None, team_id: int, asset_id: int, export_context: Mapping[str, object]
) -> str | None:
    registration = _registration(export_format, kind)
    if registration is None:
        return None
    return registration.content_path(team_id=team_id, asset_id=asset_id, export_context=export_context)


def _registration(export_format: str, kind: str | None) -> _Registration | None:
    if kind is None:
        return None
    return _export_format_handlers.get((export_format, kind))
