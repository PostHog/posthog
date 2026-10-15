import pkgutil
import importlib
from functools import cache
from typing import cast

from . import highlight_sources
from .highlight_types import Source


@cache
def load_sources() -> tuple[Source, ...]:
    return tuple(
        cast(Source, importlib.import_module(f"{highlight_sources.__name__}.{name}").SOURCE)
        for name in sorted(module.name for module in pkgutil.iter_modules(highlight_sources.__path__))
    )
