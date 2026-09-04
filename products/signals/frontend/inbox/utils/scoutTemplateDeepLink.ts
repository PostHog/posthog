import { base64Decode, base64Encode } from 'lib/utils/base64'

import { SKILL_DESCRIPTION_MAX_LENGTH, validateSkillName } from 'products/skills/frontend/skillConstants'

import type { ScoutCreateInitialValues } from '../logics/scoutCreateModalLogic'
import { SIGNALS_SCOUT_SKILL_PREFIX } from './scoutRunsWindow'
import { MAX_SCOUT_TAGS, normalizeScoutTags } from './scoutTags'

/**
 * `/inbox/config#createScout=<url-safe base64 JSON>`, e.g. from a posthog.com template page or the
 * community skills store. In the fragment so it never reaches server logs, and prefill-only: the
 * modal opens with these values and a person still submits it.
 */
export interface ScoutTemplatePayload {
    name?: string
    description?: string
    body?: string
    config?: ScoutTemplateConfig
}

/**
 * The settings a template may prefill: exactly the ones the create modal shows, so nothing a link
 * sets is hidden from the person submitting it. `network_access`, `model` and
 * `mcp_gateway_server_ids` reach into a project's data and services and never come from a link.
 */
export interface ScoutTemplateConfig {
    run_interval_minutes?: number
    run_cron_schedule?: string | null
    emit?: boolean
    tags?: string[]
}

/** Whole-payload cap, before decoding. Far above any real template, far below abuse territory. */
const MAX_ENCODED_LENGTH = 16384
const MAX_BODY_LENGTH = 20000
/** Matches the bounds the create form and the API hold a scout's cadence to. */
const MIN_RUN_INTERVAL_MINUTES = 30
const MAX_RUN_INTERVAL_MINUTES = 43200
const CRON_FIELD_COUNT = 5
const MAX_CRON_SCHEDULE_LENGTH = 100

/** Encode a template as a URL-safe base64 fragment value (used by tests and by link authors). */
export function encodeScoutCreateTemplate(template: ScoutTemplatePayload): string {
    return base64Encode(JSON.stringify(template)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Keep the prefillable settings, dropping any field that isn't one or isn't in range. */
function cleanConfig(raw: unknown): ScoutTemplateConfig | null {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
        return null
    }
    const { run_interval_minutes, run_cron_schedule, emit, tags } = raw as Record<string, unknown>
    const config: ScoutTemplateConfig = {}

    if (
        typeof run_interval_minutes === 'number' &&
        Number.isInteger(run_interval_minutes) &&
        run_interval_minutes >= MIN_RUN_INTERVAL_MINUTES &&
        run_interval_minutes <= MAX_RUN_INTERVAL_MINUTES
    ) {
        config.run_interval_minutes = run_interval_minutes
    }
    if (
        typeof run_cron_schedule === 'string' &&
        run_cron_schedule.trim().length <= MAX_CRON_SCHEDULE_LENGTH &&
        run_cron_schedule.trim().split(/\s+/).length === CRON_FIELD_COUNT
    ) {
        config.run_cron_schedule = run_cron_schedule.trim()
    }
    if (typeof emit === 'boolean') {
        config.emit = emit
    }
    if (Array.isArray(tags) && tags.every((tag) => typeof tag === 'string')) {
        // Normalized here rather than trusted: the tag editor writes normalized tags, so an
        // unnormalized one from a link would be an entry the user cannot reproduce by typing it.
        config.tags = normalizeScoutTags(tags as string[]).slice(0, MAX_SCOUT_TAGS)
    }

    return Object.keys(config).length > 0 ? config : null
}

/** Decodes a `#createScout=` value into modal initial values. Null means ignore the fragment. */
export function decodeScoutCreateTemplate(raw: unknown): ScoutCreateInitialValues | null {
    if (typeof raw !== 'string' || raw.length === 0 || raw.length > MAX_ENCODED_LENGTH) {
        return null
    }

    let parsed: unknown
    try {
        // Accept both base64 alphabets and missing padding, like the desktop deep-link decoder.
        const normalized = raw.replace(/-/g, '+').replace(/_/g, '/')
        const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
        parsed = JSON.parse(base64Decode(padded))
    } catch {
        return null
    }

    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return null
    }

    const { name, description, body, config } = parsed as Record<string, unknown>
    const cleanDescription =
        typeof description === 'string' ? description.trim().slice(0, SKILL_DESCRIPTION_MAX_LENGTH) : ''
    const cleanBody = typeof body === 'string' ? body.trim().slice(0, MAX_BODY_LENGTH) : ''

    // A link that prefills nothing but a name is indistinguishable from noise — require substance.
    if (!cleanDescription && !cleanBody) {
        return null
    }

    let cleanName = typeof name === 'string' ? name.trim() : ''
    if (cleanName && !cleanName.startsWith(SIGNALS_SCOUT_SKILL_PREFIX)) {
        cleanName = `${SIGNALS_SCOUT_SKILL_PREFIX}${cleanName}`
    }
    if (cleanName && validateSkillName(cleanName)) {
        // Invalid name: drop it so the form's default prefix stands rather than the link failing.
        cleanName = ''
    }

    const cleanedConfig = cleanConfig(config)

    return {
        ...(cleanName ? { name: cleanName } : {}),
        ...(cleanDescription ? { description: cleanDescription } : {}),
        ...(cleanBody ? { body: cleanBody } : {}),
        ...(cleanedConfig ? { config: cleanedConfig } : {}),
    }
}
