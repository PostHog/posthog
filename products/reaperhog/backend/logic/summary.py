from collections import Counter
from collections.abc import Sequence

from products.reaperhog.backend.facade.enums import ClusterRank
from products.reaperhog.backend.logic.converge import ClusterDraft
from products.reaperhog.backend.logic.inventory import ScanOutcome

_LISTED_PER_SECTION = 40


def render_summary(
    *,
    repository: str,
    scope: str,
    head_sha: str,
    drafts: Sequence[ClusterDraft],
    outcome: ScanOutcome,
    failed_scouts: Sequence[str] = (),
) -> str:
    strong = [d for d in drafts if d.strong]
    weak = [d for d in drafts if d.rank == ClusterRank.WEAK and d.blocked_reason is None]
    blocked = [d for d in drafts if d.blocked_reason is not None]
    by_kind = Counter(d.root_kind.value for d in drafts)
    by_scout = Counter(scout for d in drafts for scout in d.scouts)

    lines = [
        f"# ReaperHog scan: {repository} @ {head_sha[:12]} (scope `{scope}`)",
        "",
        f"{len(drafts)} clusters: {len(strong)} strong, {len(weak)} weak, {len(blocked)} blocked.",
        f"Inventory: {outcome.created} new, {outcome.refreshed} refreshed, {outcome.reopened} reopened, {outcome.vanished} vanished.",
        "By root: " + ", ".join(f"{kind} {count}" for kind, count in sorted(by_kind.items())) + ".",
        "By scout: " + ", ".join(f"{scout} {count}" for scout, count in sorted(by_scout.items())) + ".",
        "",
    ]
    if failed_scouts:
        lines += ["Scouts that failed this run (their roots are missing above): " + ", ".join(failed_scouts) + ".", ""]
    lines += _section("Strong candidates (harvestable)", strong)
    lines += _section("Weak candidates (needs a human)", weak)
    lines += _section("Blocked (too big for one PR)", blocked)
    return "\n".join(lines).rstrip() + "\n"


def _section(title: str, drafts: Sequence[ClusterDraft]) -> list[str]:
    lines = [f"## {title}: {len(drafts)}", ""]
    if not drafts:
        lines.append("None.")
        lines.append("")
        return lines
    for draft in drafts[:_LISTED_PER_SECTION]:
        size = f"{draft.line_count} lines" if draft.root_kind == "directory" else f"{len(draft.files)} files"
        owner = f", owner {draft.owner}" if draft.owner else ""
        lines.append(f"- `{draft.root}` ({draft.root_kind}, {size}, scouts: {', '.join(draft.scouts)}{owner})")
        for hit in draft.hits:
            lines.append(f"  - {hit.scout}: {hit.summary}")
    if len(drafts) > _LISTED_PER_SECTION:
        lines.append(f"- ... and {len(drafts) - _LISTED_PER_SECTION} more")
    lines.append("")
    return lines
