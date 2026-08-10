"""The muted line under a finished reply: where to open the run, what produced it, and
where to change that.

Pure Block Kit assembly, like the other builders under `services/` — no Slack client and
no database, so the footer's shape can be tested on its own. `SlackThreadHandler` owns
the flag gate and hands these functions the values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from posthog.models.integration import Integration

from products.slack_app.backend.services.model_catalogue import describe_run_model


@dataclass(frozen=True)
class RunProvenance:
    """What a reply can say about the run behind it.

    Constant for the life of a handler, so it is supplied once at construction rather
    than threaded through every posting method. An empty instance is the "say nothing"
    case, which is what every caller outside the footer rollout gets.
    """

    task_url: str | None = None
    desktop_url: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None

    def __bool__(self) -> bool:
        """False when there is nothing to describe, so a caller can skip the gate —
        and the queries behind it — rather than resolve a footer that can't render."""
        return any((self.task_url, self.desktop_url, self.model))


def app_home_url(integration: Integration) -> str | None:
    """Deep link to this install's Home tab, where the model picker lives.

    The `app_redirect` form is https, so it survives as a link in any client and in a
    browser; `slack://app` only resolves natively. Both need the app id (`A…`), which the
    OAuth exchange already persisted on the integration — so this stays correct even
    where more than one Slack app is in play. A row installed by some other path may not
    carry it, which simply means no link.
    """
    app_id = (integration.config or {}).get("app_id")
    if not app_id or not integration.integration_id:
        return None
    return f"https://slack.com/app_redirect?app={app_id}&team={integration.integration_id}&tab=home"


def reply_footer_block(
    provenance: RunProvenance | None = None,
    configure_url: str | None = None,
) -> dict[str, Any] | None:
    """The footer as a `context` block, or `None` when there is nothing to say.

    The answer itself is the message, so this is muted rather than competing with the
    prose. A run with no links and no pinned model contributes no segments and gets no
    trailing line at all.
    """
    provenance = provenance or RunProvenance()
    segments: list[str] = []
    if provenance.task_url:
        segments.append(f"<{provenance.task_url}|View on web>")
    if provenance.desktop_url:
        segments.append(f"<{provenance.desktop_url}|View on desktop>")
    if provenance.model:
        segments.append(describe_run_model(provenance.model, provenance.reasoning_effort))
    if configure_url:
        segments.append(f"<{configure_url}|Configure>")
    if not segments:
        return None
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(segments)}]}
