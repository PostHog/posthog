import type { AuthPolicy, CompiledAgent, SkillSpec, ToolSpec, TriggerConfig } from '@repo/ass-server'

import { logger } from '../logger'
import type { ResolvedRevision } from './types'

/**
 * Translate a PostHog-side `ResolvedRevision` (DB row materialized by
 * `ApplicationsRepository`) into the shared `CompiledAgent` shape that
 * `@repo/ass-server/route` consumes.
 *
 * v1 reads triggers / tools / skills / systemPrompt out of `parsedManifest`
 * when the validator has populated it; otherwise it falls back to safe defaults
 * (a single `http_invoke` trigger so `POST /run` is always reachable, empty
 * tools/skills lists, empty system prompt).
 *
 * The trust boundary stays the same: this function never reaches into bundle
 * code or decrypts anything. Secrets are loaded lazily by the parent via the
 * `loadSecret` callback at request time.
 */
export function compileAgent(revision: ResolvedRevision): CompiledAgent {
    const manifest = revision.parsedManifest ?? {}

    const triggers = readTriggers(manifest)
    const tools = readToolSpecs(manifest)
    const skills = readSkillSpecs(manifest)
    const systemPrompt = typeof manifest.systemPrompt === 'string' ? manifest.systemPrompt : ''
    const auth = translateAuth(revision.auth, revision.applicationSlug)

    return {
        slug: revision.applicationSlug,
        systemPrompt,
        tools,
        skills,
        triggers,
        auth,
    }
}

function readTriggers(manifest: Record<string, unknown>): TriggerConfig[] {
    const raw = manifest.triggers
    if (!Array.isArray(raw) || raw.length === 0) {
        // Default — every agent has /run unless it explicitly opts out (which
        // the schema doesn't currently support).
        return [{ id: 'http', type: 'http_invoke' }]
    }
    const out: TriggerConfig[] = []
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

function translateTrigger(entry: unknown): TriggerConfig | null {
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
        const signingSecretName = obj.signing_secret_name ?? obj.signingSecretName
        if (events.length === 0 || typeof signingSecretName !== 'string') {
            return null
        }
        return { id: obj.id, type: 'slack_event', events, signingSecretName }
    }
    return null
}

function readToolSpecs(manifest: Record<string, unknown>): ToolSpec[] {
    const raw = manifest.tools
    if (!Array.isArray(raw)) {
        return []
    }
    const out: ToolSpec[] = []
    for (const entry of raw) {
        if (typeof entry === 'string') {
            out.push({ id: entry, description: '', inputSchema: {} })
        } else if (entry && typeof entry === 'object' && typeof (entry as { id?: unknown }).id === 'string') {
            out.push({
                id: (entry as { id: string }).id,
                description:
                    typeof (entry as { description?: unknown }).description === 'string'
                        ? (entry as { description: string }).description
                        : '',
                inputSchema:
                    (entry as { inputSchema?: unknown }).inputSchema &&
                    typeof (entry as { inputSchema: unknown }).inputSchema === 'object'
                        ? (entry as { inputSchema: Record<string, unknown> }).inputSchema
                        : {},
            })
        }
    }
    return out
}

function readSkillSpecs(manifest: Record<string, unknown>): SkillSpec[] {
    const raw = manifest.skills
    if (!Array.isArray(raw)) {
        return []
    }
    const out: SkillSpec[] = []
    for (const entry of raw) {
        if (typeof entry === 'string') {
            out.push({ id: entry, name: entry, description: '', body: '' })
        } else if (entry && typeof entry === 'object' && typeof (entry as { id?: unknown }).id === 'string') {
            const o = entry as { id: string; name?: unknown; description?: unknown; body?: unknown }
            out.push({
                id: o.id,
                name: typeof o.name === 'string' ? o.name : o.id,
                description: typeof o.description === 'string' ? o.description : '',
                body: typeof o.body === 'string' ? o.body : '',
            })
        }
    }
    return out
}

function translateAuth(revisionAuth: ResolvedRevision['auth'], slug: string): AuthPolicy {
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
