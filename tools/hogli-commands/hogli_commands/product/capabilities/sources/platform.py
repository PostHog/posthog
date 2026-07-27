"""Facts that are global rather than per-product.

Some capabilities genuinely have no product attribution. The Slack CDP destination
template is available to every project and names no product; the CLI ships command groups
with no product mapping at all. Emitting a per-product boolean for either would be
fabricating attribution the repo does not have, so they are reported once, here.
"""

from __future__ import annotations

import re

from ..context import DerivationContext
from ..models import PlatformFacts

_SLACK_TEMPLATE = "posthog/cdp/templates/slack/template_slack.py"
_SIGNALS_ENUMS = "products/signals/backend/enums.py"
_CLI_SRC = "cli/src"

_ENUM_MEMBER_RE = re.compile(r'^\s+[A-Z0-9_]+\s*=\s*"([a-z0-9_]+)"', re.MULTILINE)


def _warehouse_signal_sources(ctx: DerivationContext) -> list[str]:
    """SignalSourceProduct values that are NOT product directories.

    These are the third-party systems (Sentry, Zendesk, Snyk, …) that feed the Signals
    inbox. They are a data-source registry, not a product list, which is why they belong
    at the platform level rather than being joined onto products.
    """
    path = ctx.repo_root / _SIGNALS_ENUMS
    if not path.exists():
        return []
    text = path.read_text()
    block = re.search(r"class SignalSourceProduct\(StrEnum\):(.*?)(?=\nclass )", text, re.DOTALL)
    if not block:
        return []
    values = _ENUM_MEMBER_RE.findall(block.group(1))
    return sorted({v for v in values if ctx.join(v).product is None})


def _cli_command_groups(ctx: DerivationContext) -> list[str]:
    src = ctx.repo_root / _CLI_SRC
    if not src.is_dir():
        return []
    return sorted(d.name for d in src.iterdir() if d.is_dir())


def derive(ctx: DerivationContext) -> PlatformFacts:
    return PlatformFacts(
        slack_cdp_outbound_destination=(ctx.repo_root / _SLACK_TEMPLATE).exists(),
        warehouse_signal_sources=_warehouse_signal_sources(ctx),
        cli_command_groups=_cli_command_groups(ctx),
    )
