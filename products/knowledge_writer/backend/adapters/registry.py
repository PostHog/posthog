from typing import Any

from ..facade.contracts import Adapter
from ..facade.enums import DocsRequestSource
from .command_tag import CommandTagAdapter

REGISTRY: dict[DocsRequestSource, Adapter[Any]] = {
    DocsRequestSource.COMMAND_TAG: CommandTagAdapter(),
}
