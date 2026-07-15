import sys
from pathlib import Path

# The review engine (tools/pr-approval-agent) is a set of plain modules, not an importable package, so
# its directory must be on sys.path to import its policy loader by bare name — same way its own tests do.
_ENGINE_DIR = Path(__file__).resolve().parents[4] / "tools" / "pr-approval-agent"
sys.path.insert(0, str(_ENGINE_DIR))

import policy  # noqa: E402

_DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "policy_defaults" / "policy.yml"


def test_shipped_default_policy_loads_through_engine_loader() -> None:
    # The hosted default policy.yml must satisfy the engine's own loader (all required sections,
    # self-governance deny, valid regexes) — otherwise every zero-config repo crashes at review time.
    loaded = policy.load_policy(
        _DEFAULT_POLICY,
        lockfile_names=["package-lock.json", "uv.lock"],
        ownership_formats={"gh-codeowners": "path", "ph-product": "glob"},
    )
    assert loaded.version == 1
