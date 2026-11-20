import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from products.tasks.backend.logic.services import gateway_models
from products.tasks.backend.logic.services.gateway_models import GatewayModel

_SAVED_LISTING = Path(__file__).parents[1] / "tests" / "fixtures" / "gateway_models.json"

__all__ = ["saved_gateway_listing", "serve_gateway_listing"]


@cache
def saved_gateway_listing() -> tuple[GatewayModel, ...]:
    rows = json.loads(_SAVED_LISTING.read_text())["data"]
    return tuple(gateway_models._gateway_model(SimpleNamespace(**row)) for row in rows)


class _ServedListing:
    def __init__(self, listing: tuple[GatewayModel, ...]) -> None:
        self._listing = listing

    def get(self, key: str, default: Any = None) -> tuple[GatewayModel, ...]:
        return self._listing

    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        return None


@contextmanager
def serve_gateway_listing(listing: tuple[GatewayModel, ...] | None = None) -> Iterator[None]:
    served = saved_gateway_listing() if listing is None else listing
    with patch.object(gateway_models, "cache", _ServedListing(served)):
        yield
