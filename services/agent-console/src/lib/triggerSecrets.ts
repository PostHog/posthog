/**
 * Hand-rolled mirror of `TRIGGER_REQUIRED_SECRETS` from `@posthog/agent-shared`
 * (`src/spec/trigger-secrets.ts`). Kept here — same reasoning as `types/mcp.ts`
 * — to avoid pulling the agent-shared workspace into the console's bundle.
 * Keep in lockstep with both the agent-shared TS source and the Django mirror
 * in `products/agent_platform/backend/spec_schema.py`.
 *
 * Used by the Connections tab to surface trigger-derived required secrets
 * (e.g. Slack's signing secret + bot token) alongside the spec's top-level
 * `secrets[]` declarations, so "missing secrets" isn't blind to triggers.
 */

export const SLACK_SIGNING_SECRET_KEY = 'SLACK_SIGNING_SECRET'
export const SLACK_BOT_TOKEN_KEY = 'SLACK_BOT_TOKEN'

export interface TriggerSecretRequirement {
    key: string
    label: string
    description: string
    required: boolean
}

const TRIGGER_REQUIRED_SECRETS: Record<string, TriggerSecretRequirement[]> = {
    chat: [],
    webhook: [],
    cron: [],
    mcp: [],
    slack: [
        {
            key: SLACK_SIGNING_SECRET_KEY,
            label: 'Slack signing secret',
            description:
                "Your Slack app's signing secret. Find it under Settings → Basic Information → Signing Secret. Required to verify inbound Slack event signatures.",
            required: true,
        },
        {
            key: SLACK_BOT_TOKEN_KEY,
            label: 'Slack bot user OAuth token',
            description:
                "Your Slack app's bot token (starts with `xoxb-`). Find it under Settings → Install App → Bot User OAuth Token after installing the app to your workspace. Used by native slack tools to call the Slack API.",
            required: true,
        },
    ],
}

/** A trigger-required secret, annotated with which trigger type contributed it. */
export interface DerivedTriggerSecret extends TriggerSecretRequirement {
    trigger: string
}

/**
 * Walk `spec.triggers` and return the per-trigger required secrets, deduped
 * by key (first trigger to require a key wins for the `trigger` annotation).
 * Mirrors `missing_required_secrets` in the Django spec_schema but returns
 * everything (set or unset) so the UI can render them as part of the
 * declared-secrets list.
 */
export function getTriggerRequiredSecrets(spec: Record<string, unknown>): DerivedTriggerSecret[] {
    const triggers = spec.triggers
    if (!Array.isArray(triggers)) {
        return []
    }
    const seen = new Set<string>()
    const out: DerivedTriggerSecret[] = []
    for (const trigger of triggers) {
        if (typeof trigger !== 'object' || trigger === null) {
            continue
        }
        const type = (trigger as { type?: unknown }).type
        if (typeof type !== 'string') {
            continue
        }
        const requirements = TRIGGER_REQUIRED_SECRETS[type] ?? []
        for (const req of requirements) {
            if (!req.required || seen.has(req.key)) {
                continue
            }
            seen.add(req.key)
            out.push({ ...req, trigger: type })
        }
    }
    return out
}
