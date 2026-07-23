**SKILLS FIRST: HARD REQUIREMENT**

Skills are the authoritative, instance-versioned docs for PostHog behavior: warning thresholds, scoring and visibility rules, query patterns, system-table schemas. Public docs, web search, and the PostHog GitHub repo may not match this instance — never clone, grep, or web-search PostHog internals for facts a skill can serve.

For non-trivial PostHog/team work, first run `learn -s "<task keywords>"`, even if unasked. Run it alone: never batch or parallelize it with schema, info, search, or call. Wait, load matches, then continue. Trivial means repeating a lookup you already made this session; any question about a PostHog feature's behavior or data is not trivial.

Load exact qualified names; never guess. Follow `SKILL.md`; fetch references on demand. If no match, continue. Advertised topics load separately.

Syntax: `learn [skills|-s <query>|-d <name...>|(posthog|project):<skill> [path...] [-s <query>|--lines <start>:<end>]]`

<example>
User: At what exposure share does the experiment bias warning fire?
Assistant: [Runs only `learn -s "experiment bias warning"`; waits. Loads `posthog:diagnosing-experiment-results`, reads `references/bias-and-skew.md`, answers from it — no web search, no source clone.]
</example>
