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
    const manifest = revision.parsedManifest ?? {}

    const triggers = readTriggers(manifest)
    const tools = readStringIds(manifest.tools)
    const skills = readStringIds(manifest.skills)
    const prompt = typeof manifest.prompt === 'string' ? manifest.prompt : ''
    const auth = translateAuth(revision.auth, revision.applicationSlug)

    return {
        name: revision.applicationSlug,
        slug: revision.applicationSlug,
        prompt,
        tools,
        skills,
        triggers,
        auth,
        visibility: auth?.type === 'public' ? 'public' : 'private',
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
        // Accept both snake_case (canonical, how it's written in agent.ts and the
        // bundler-produced manifest) and the legacy camelCase form for
        // forward-compat with any older revision rows.
        const signingSecretName = obj.signing_secret_name ?? obj.signingSecretName
        if (events.length === 0 || typeof signingSecretName !== 'string') {
            return null
        }
        return { id: obj.id, type: 'slack_event', events, signing_secret_name: signingSecretName }
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

function translateAuth(revisionAuth: ResolvedRevision['auth'], slug: string): AgentDefinition['auth'] {
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
            // Schema trim dropped shared_secret; falling back to public until
            // legacy revisions are migrated to `pat` or `webhook_signature`.
            logger.warn('compileAgent: shared_secret auth no longer supported, falling back to public', { slug })
            return { type: 'public' }
    }
}
