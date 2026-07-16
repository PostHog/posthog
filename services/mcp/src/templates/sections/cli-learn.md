**SKILLS FIRST: HARD REQUIREMENT**

For non-trivial PostHog/team work, first run `learn -s "<task keywords>"`, even if unasked. Run it alone: never batch or parallelize it with schema, info, search, or call. Wait, load matches, then continue. Skip only trivial lookups or unrelated chat.

Load exact qualified names; never guess. Follow `SKILL.md`; fetch references on demand. If no match, continue. Advertised topics load separately.

Syntax: `learn [skills|-s <query>|(posthog|project):<skill> [path] [-s <query>|--lines <start>:<end>]]`

<example>
User: Investigate why checkout conversion dropped this week.
Assistant: [Runs only `learn -s "checkout conversion drop"`; waits. Gets `posthog:investigate-metric`; loads it exactly, follows it, then discovers tools.]
</example>
