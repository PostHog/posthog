"""Reference implementations of `CustomSignalAgent` subclasses.

These exist as living documentation:

- `cookie_poem_agent.py` — the canonical minimal example (NO_REPO, static components).
- `cursed_comment_agent.py` — a realistic example that researches a repo and lets the default
  resolvers fill actionability/priority/assignees agentically.

Run either via `python manage.py run_custom_agent_example --agent {cookie_poem,cursed_comment}`.
"""
