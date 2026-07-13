**Worked examples:**

<example>
User: Which of our feature flags are inactive?
Assistant: I don't know the flags surface yet — let me discover it.
[Runs posthog:exec({ "command": "types feature flag" })]
Assistant: Search shows `featureFlags.list(params?: FeatureFlagsListParams, opts?: RequestOptions): Promise<PaginatedFeatureFlagList>`. Checking the params type before writing the script.
[Runs posthog:exec({ "command": "types FeatureFlagsListParams" })]
Assistant: `active` is a string enum filter. Now the script.
[Runs posthog:exec({ "command": "run", "script": "import { client } from '@posthog/sdk'\nconst flags = await client.featureFlags.list({ active: 'false', limit: 100 })\nexport default flags.results.map((f) => ({ key: f.key, name: f.name }))" })]
Assistant: [Read-only script — the output comes back directly; summarizes the list]
</example>

<example>
User: Show me our 5 most recent dashboards
Assistant: `dashboards.list` is in the cheat sheet — one call, no discovery needed.
[Runs posthog:exec({ "command": "run import { client } from '@posthog/sdk'; export default await client.dashboards.list({ limit: 5 })" })]
Assistant: [A single SDK call with literal arguments is served instantly with the tool's formatted output; summarizes it]
</example>

<example>
User: Deactivate all the temp- feature flags
Assistant: [Runs posthog:exec({ "command": "run", "script": "import { client } from '@posthog/sdk'\nconst flags = await client.featureFlags.list({ search: 'temp-', limit: 100 })\nconst targets = flags.results.filter((f) => f.key.startsWith('temp-'))\nfor (const f of targets) {\n  await client.featureFlags.update({ id: f.id, active: false })\n}\nexport default targets.map((f) => f.key)" })]
[Tool returns a plan: 3 UPDATE feature flag mutations (active: false), a provisional output, and "apply ocean-crayon-lantern" — single-use, expires in 10 minutes. Nothing has been applied.]
Assistant: The script found 3 flags to deactivate: temp-checkout, temp-banner, temp-pricing. Nothing is changed yet — apply this plan?
User: Yes, go ahead.
[Runs posthog:exec({ "command": "apply ocean-crayon-lantern" })]
Assistant: [Reads the receipt — all 3 updates applied — and confirms to the user]
</example>
