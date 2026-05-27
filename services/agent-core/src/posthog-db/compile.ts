import type { AgentDefinition, TriggerDefinition } from '@repo/ass-server'

import { logger } from '../logger'
import type { ResolvedRevision } from './types'

/**
 * Translate a PostHog-side `ResolvedRevision` (DB row materialized by
 * `ApplicationsRepository`) into the shared `AgentDefinition` shape that
 * `@repo/ass-server/route` consumes.
 *
 * v1 reads triggers / tools / skills / prompt out of `parsedManifest` when the
 * validator has populated it; otherwise it falls back to safe defaults — a
 * single `http_invoke` trigger so `POST /run` is always reachable, empty
 * tools/skills lists, empty prompt.
 *
 * The trust boundary stays the same: this function never reaches into bundle
 * code or decrypts anything. Secrets are loaded lazily by the parent via the
 * `loadSecret` callback at request time.
 */
export function compileAgent(revision: ResolvedRevision): AgentDefinition {
    // The async validator (services/agent-validator/) is deferred — it's what
    // will populate `parsed_manifest`. Until it ships, the runner reads the
    // bundler-emitted `top_level_config` directly. Either yields the same
    // `triggers` / `tools` / `prompt` shape since `agentDefinitionToAssYaml`
    // is the canonical producer.
    const manifest = revision.parsedManifest ?? revision.topLevelConfig ?? {}

    const triggers = readTriggers(manifest)
    const tools = readStringIds(manifest.tools)
    const skills = readStringIds(manifest.skills)
    const prompt = typeof manifest.prompt === 'string' ? manifest.prompt : ''
    const model = typeof manifest.model === 'string' && manifest.model.length > 0 ? manifest.model : undefined
    // Prefer the agent.yaml-shape auth on the manifest (`{type, ...}`); fall
    // back to the legacy ResolvedRevision.auth (`{mode, ...}`) for old revisions
    // whose top_level_config was emitted before pat / posthog_internal landed.
    const auth = readManifestAuth(manifest.auth) ?? translateLegacyAuth(revision.auth, revision.applicationSlug)
    const identity = readIdentity(manifest.identity)

    return {
        name: revision.applicationSlug,
        slug: revision.applicationSlug,
        prompt,
        model,
        tools,
        skills,
        triggers,
        auth,
        identity,
        visibility: auth?.type === 'public' ? 'public' : 'private',
    }
}

/**
 * Read the canonical agent.yaml-shape auth block (`{type: 'pat' | 'posthog_internal' | …, ...}`)
 * straight off the manifest. Returns `undefined` (not `null`) when absent so
 * the caller falls back to the legacy `ResolvedRevision.auth`. Loose typing —
 * the canonical zod validation lives in ass-config; this just narrows the
 * union for `route()` consumers.
 */
function readManifestAuth(raw: unknown): AgentDefinition['auth'] | undefined {
    if (!raw || typeof raw !== 'object') {
        return undefined
    }
    const obj = raw as { type?: unknown; [k: string]: unknown }
    if (typeof obj.type !== 'string') {
        return undefined
    }
    return obj as { type: string; [k: string]: unknown }
}

/**
 * Read the `identity:` block, loose-typed for the same reason as `auth`.
 * `space` is required; `source.provider` is the only piece the Slack trigger
 * narrows on at runtime. Everything else passes through unmodified.
 */
function readIdentity(raw: unknown): AgentDefinition['identity'] {
    if (!raw || typeof raw !== 'object') {
        return undefined
    }
    const obj = raw as { space?: unknown; source?: unknown }
    if (typeof obj.space !== 'string' || !obj.source || typeof obj.source !== 'object') {
        return undefined
    }
    const src = obj.source as { provider?: unknown; [k: string]: unknown }
    if (typeof src.provider !== 'string') {
        return undefined
    }
    return {
        space: obj.space,
        source: src as { provider: string; [k: string]: unknown },
    }
}

function readTriggers(manifest: Record<string, unknown>): TriggerDefinition[] {
    const raw = manifest.triggers
    if (!Array.isArray(raw) || raw.length === 0) {
        // Default — every agent has /run unless it explicitly opts out (which
        // the schema doesn't currently support).
        return [{ id: 'http', type: 'http_invoke' }]
    }
    const out: TriggerDefinition[] = []
    for (const entry of raw) {
        const trigger = translateTrigger(entry)
        if (trigger) {
            out.push(trigger)
        }
    }
    if (out.length === 0) {
        return [{ id: 'http', type: 'http_invoke' }]
    }
    return out
}

function translateTrigger(entry: unknown): TriggerDefinition | null {
    if (!entry || typeof entry !== 'object') {
        return null
    }
    const obj = entry as Record<string, unknown>
    if (typeof obj.id !== 'string' || typeof obj.type !== 'string') {
        return null
    }
    if (obj.type === 'http_invoke') {
        return { id: obj.id, type: 'http_invoke' }
    }
    if (obj.type === 'slack_event') {
        const events = Array.isArray(obj.events) ? obj.events.filter((e): e is string => typeof e === 'string') : []
        if (events.length === 0) {
            return null
        }
        // The trigger handler sources `SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN`
        // from well-known env-var names (see packages/ass-server/src/triggers/slack.ts) —
        // no per-instance config. Older revisions whose manifest still carries
        // `signing_secret_name` are forward-compatible because the handler
        // ignores it.
        return { id: obj.id, type: 'slack_event', events }
    }
    return null
}

/**
 * Normalize a `tools:` / `skills:` manifest entry into a flat list of ids.
 * The new `AgentDefinition` schema only carries ids (string[]); any richer
 * descriptions live on the registered builtin / loaded local-tool side.
 */
function readStringIds(raw: unknown): string[] {
    if (!Array.isArray(raw)) {
        return []
    }
    const out: string[] = []
    for (const entry of raw) {
        if (typeof entry === 'string') {
            out.push(entry)
        } else if (entry && typeof entry === 'object' && typeof (entry as { id?: unknown }).id === 'string') {
            out.push((entry as { id: string }).id)
        }
    }
    return out
}

function translateLegacyAuth(revisionAuth: ResolvedRevision['auth'], slug: string): AgentDefinition['auth'] {
    switch (revisionAuth.mode) {
        case 'public':
            return { type: 'public' }
        case 'webhook_signature':
            if (revisionAuth.provider !== 'slack') {
                logger.warn('compileAgent: webhook_signature provider not supported, falling back to public', {
                    slug,
                    provider: revisionAuth.provider,
                })
                return { type: 'public' }
            }
            return { type: 'webhook_signature', provider: 'slack' }
        case 'shared_secret':
            // Schema trim dropped legacy `shared_secret` (the one with a
            // raw token field on ResolvedRevision). The new `shared_secret`
            // policy uses `secret_name` + a custom header and comes through
            // `readManifestAuth` above. Fall back to public for old rows.
            logger.warn('compileAgent: legacy shared_secret auth no longer supported, falling back to public', { slug })
            return { type: 'public' }
    }
}
