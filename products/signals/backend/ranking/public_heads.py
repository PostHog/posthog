"""The outcome heads of the ranking model that the API, the inbox sorts and the MCP tools show by name.

The served model scores more heads than these. The other heads stay readable in `ranking_score` artefacts and
through their `ranking_<head>` ordering fields, but the `ranking` field, the ranking filters and the heads list
show only the heads here, in this order. Add a head here to show it everywhere at once.

Horizon and cohort come from the served model's metadata, not from this file, so they follow the model.
"""

from typing import Literal, get_args

from posthog.dataclasses import frozen

PublicHeadName = Literal["open", "action", "fixed"]


@frozen
class PublicHead:
    head: PublicHeadName
    label: str
    description: str


PUBLIC_HEADS: tuple[PublicHead, ...] = (
    PublicHead(
        head="open",
        label="Open",
        description="Chance that a person opens the report within the horizon. A prediction, not the report's state.",
    ),
    PublicHead(
        head="action",
        label="Engage",
        description=(
            "Chance that a person or their agent acts on the report within the horizon. "
            "A prediction, not the report's state."
        ),
    ),
    PublicHead(
        head="fixed",
        label="Fix",
        description=(
            "Chance that someone fixes the problem the report describes within the horizon. "
            "A prediction, not the report's status."
        ),
    ),
)

PUBLIC_HEAD_NAMES: tuple[PublicHeadName, ...] = tuple(entry.head for entry in PUBLIC_HEADS)

assert PUBLIC_HEAD_NAMES == get_args(PublicHeadName), "PUBLIC_HEADS and PublicHeadName must list the same heads"
