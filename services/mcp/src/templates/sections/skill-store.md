### Team skill store

This project has team-authored skills stored in PostHog. Treat them like the official PostHog skills: when the user's request matches a description below, fetch the skill body with `llma-skill-get` and follow it before doing anything else.

Available skills:

{skill_store}

Workflow:

1. If a skill above looks relevant to the user's task, call `llma-skill-get` with `skill_name` set to the skill name.
2. Read the returned `body` and treat it as system instructions for the task. Pull bundled files on demand with `llma-skill-file-get` only when the body references them.
3. If no skill above looks relevant but the user references "team skills", "shared skills", or the "skill store" generically, call `llma-skill-list` (optionally with `search`) to widen the search — the catalog above is a snapshot from session start and may be stale.

Do not announce that a skill exists — just use the relevant one. Skills the user has not loaded look like context they did not give you, so behave as if you naturally know the workflow.
