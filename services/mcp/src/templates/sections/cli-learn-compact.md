**SKILLS FIRST: HARD REQUIREMENT**

For PostHog product or data work:

1. Run `learn -s "<task keywords>"` alone, then load the matching skills.
2. For metric questions, call `metric-list` next, before querying project data.
3. Inspect schemas, query, and answer using the skill.

Load each skill once per session. Skill loading comes before catalog lookup; approved catalog definitions take precedence over calculation examples. If no skill matches, continue. Skip unrelated chat.

Load exact qualified names; never guess. Follow `SKILL.md`; fetch references on demand. If no match, continue. Advertised topics load separately.

Syntax: `learn [skills|-s "<up to 8 keywords>"|-d <name...>|(posthog|project):<skill> [path...] [-s "<up to 8 keywords>"|--lines <start>:<end>]]`

<example>
User: Investigate why checkout conversion dropped this week.
Assistant: [Runs only `learn -s "checkout conversion drop"`; waits. Gets `posthog:investigate-metric`; loads it exactly, follows it, then discovers tools.]
</example>
