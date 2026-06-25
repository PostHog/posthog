from pathlib import Path

# Instruction handed to the task agent for a cloud wizard run: the wizard has already integrated
# PostHog, so the agent only commits the changes, opens the PR, and keeps it green — it never
# implements PostHog itself. Kept as a markdown file (read once at import) so it can be reviewed and
# edited as prose rather than buried in a string literal.
WIZARD_PR_AGENT_PROMPT = (
    (Path(__file__).resolve().parent.parent / "prompts" / "wizard_pr_agent_prompt.md").read_text(encoding="utf-8")
).strip()
