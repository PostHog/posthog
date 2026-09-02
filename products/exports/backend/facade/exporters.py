from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.exports.backend.models.exported_asset import ExportedAsset


ExportFormatHandler = Callable[["ExportedAsset"], None]

_export_format_handlers: dict[str, ExportFormatHandler] = {}


def register_export_format_handler(export_format: str, handler: ExportFormatHandler) -> None:
    existing_handler = _export_format_handlers.get(export_format)
    if existing_handler is not None and existing_handler is not handler:
        raise ValueError(f"An export handler is already registered for {export_format}.")
    _export_format_handlers[export_format] = handler


def get_export_format_handler(export_format: str) -> ExportFormatHandler | None:
    return _export_format_handlers.get(export_format)
