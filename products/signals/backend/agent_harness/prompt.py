from __future__ import annotations

from products.signals.backend.agent_harness.skill_loader import LoadedSkill

# Phase 2 base prompt. Intentionally bare-bones: the goal is to prove the harness
# can spawn a sandbox, run a prompt to completion, and persist the result. Phase 4
# replaces this with the real identity / output contract / dedupe rules.
_BASE_PROMPT_HEADER = """You are a Signals scout agent for PostHog.

This is a scaffolding run — the harness is verifying it can spawn you, hand you a
skill, and capture your reply. Read the skill below and respond with a one-paragraph
summary of what you would investigate if you were given a real budget.

Do not call any tools yet. Do not emit any signals. Do not take action."""


def build_run_prompt(skill: LoadedSkill) -> str:
    """Render the opening prompt for one Phase-2 scout run."""
    file_manifest = "\n".join(f"- {f.path} ({f.content_type})" for f in skill.files) or "(none)"
    return f"""{_BASE_PROMPT_HEADER}

---

## Bound skill: `{skill.name}` (v{skill.version})

{skill.description}

### Skill body

{skill.body}

### Skill files

{file_manifest}
"""
