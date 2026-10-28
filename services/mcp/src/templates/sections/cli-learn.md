**SKILLS FIRST: HARD REQUIREMENT**

Skills are the authoritative, instance-versioned docs for PostHog behavior: warning thresholds, scoring and visibility rules, query patterns, system-table schemas. Public docs, web search, and the PostHog GitHub repo may not match this instance — never clone, grep, or web-search PostHog internals for facts a skill can serve.

For PostHog product or data work:

1. Run `learn -s "<task keywords>"` alone, then load the matching skills.
2. For metric questions, call `metric-list` next, before querying project data.
3. Inspect schemas, query, and answer using the skill.

Load each skill once per session. Skill loading comes before catalog lookup; approved catalog definitions take precedence over calculation examples. If no skill matches, continue. Skip unrelated chat.

Load exact qualified names; never guess. Follow `SKILL.md`; fetch references on demand. If no match, continue. Advertised topics load separately.

Syntax: `learn [skills|-s "<up to 8 keywords>"|-d <name...>|(posthog|project):<skill> [path...] [-s "<up to 8 keywords>"|--lines <start>:<end>]]`

<example>
User: At what exposure share does the experiment bias warning fire?
Assistant: [Runs only `learn -s "experiment bias warning"`; waits. Loads `posthog:diagnosing-experiment-health`, reads `references/bias-and-skew.md`, answers from it — no web search, no source clone.]
</example>
