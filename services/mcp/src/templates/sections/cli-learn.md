**SKILLS FIRST: HARD REQUIREMENT**

For non-trivial PostHog/team work, first run `learn -s "<task keywords>"`, even if unasked. Run it alone: do not batch or parallelize it with schema, info, search, or call. Wait, load matches, then continue. Skip only trivial lookups or unrelated chat.

Load exact qualified names; never guess. Follow `SKILL.md`; fetch references on demand. If no match, continue. Advertised topics load separately.

Syntax: `learn [skills|-s <query>|(posthog|project):<skill> [path] [-s <query>|--lines <start>:<end>]]`

<example>
User: Investigate why checkout conversion dropped this week.
Assistant: [Runs only `posthog:exec({ "command": "learn -s \"checkout conversion drop investigation\"" })`; waits.]
[Gets `posthog:investigate-metric`; loads it exactly, follows it, then discovers tools.]
</example>

<bad-example>
User: Investigate a drop in retention.
Assistant: [Runs `learn -s "retention drop"` with `call read-data-schema {…}`.]
WRONG: Search alone; wait, load the match, then query data.
</bad-example>
