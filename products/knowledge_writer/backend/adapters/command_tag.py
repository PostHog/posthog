from typing import ClassVar

from ..facade.enums import DocsRequestSource


class CommandTagAdapter:
    source: ClassVar[DocsRequestSource] = DocsRequestSource.COMMAND_TAG
    instructions: ClassVar[str] = (
        "A teammate asked for this docs change with the docs command, and the docs check agreed. "
        "Read the merged commit to learn what shipped, then change the docs pages it affects."
    )
