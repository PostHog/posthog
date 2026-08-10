"""The muted line under a finished reply: where to open the run, what produced it, and
where to change that.

Pure Block Kit assembly, like the other builders under `services/` — no Slack client and
no database, so the footer's shape can be tested on its own. `SlackThreadHandler` owns
the flag gate and hands these functions the values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from products.slack_app.backend.services.blocks import context_block
from products.slack_app.backend.services.model_catalogue import describe_run_model


@dataclass(frozen=True)
class RunFooter:
    """What a reply can say about the run behind it.

    Constant for the life of a handler, so it is supplied once at construction rather
    than threaded through every posting method. An empty instance is the "say nothing"
    case, which is what every caller outside the footer rollout gets.
    """

    task_url: str | None = None
    desktop_url: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None

    def has_content(self) -> bool:
        """Whether this would render as anything.

        A caller checks it to skip the flag lookups behind a footer that can't appear.
        Spelled out rather than given as ``__bool__`` so that ``footer or RunFooter()``
        keeps meaning "None-coalesce" and cannot silently discard a partial instance.
        """
        return any((self.task_url, self.desktop_url, self.model))


def reply_footer_block(footer: RunFooter, configure_url: str | None = None) -> dict[str, Any] | None:
    """The footer as a `context` block, or `None` when there is nothing to say.

    The answer itself is the message, so this is muted rather than competing with the
    prose. A run with no links and no pinned model contributes no segments and gets no
    trailing line at all.
    """
    segments: list[str] = []
    if footer.task_url:
        segments.append(f"<{footer.task_url}|View on web>")
    if footer.desktop_url:
        segments.append(f"<{footer.desktop_url}|View on desktop>")
    if footer.model:
        segments.append(describe_run_model(footer.model, footer.reasoning_effort))
    if configure_url:
        segments.append(f"<{configure_url}|Configure>")
    if not segments:
        return None
    return context_block(" · ".join(segments))
