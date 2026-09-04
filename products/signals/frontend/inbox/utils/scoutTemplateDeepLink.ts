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

/** `{ key: value }` when the cleaner kept the value, and nothing when it dropped it. */
function defined<K extends string, V>(key: K, value: V | undefined): Partial<Record<K, V>> {
    return value === undefined ? {} : ({ [key]: value } as Record<K, V>)
}

/** The cadence, or undefined when the link gave none the create form would accept. */
function cleanInterval(value: unknown): number | undefined {
    if (typeof value !== 'number' || !Number.isInteger(value)) {
        return undefined
    }
    return value >= MIN_RUN_INTERVAL_MINUTES && value <= MAX_RUN_INTERVAL_MINUTES ? value : undefined
}

function cleanCron(value: unknown): string | undefined {
    if (typeof value !== 'string') {
        return undefined
    }
    const schedule = value.trim()
    if (schedule.length > MAX_CRON_SCHEDULE_LENGTH) {
        return undefined
    }
    return schedule.split(/\s+/).length === CRON_FIELD_COUNT ? schedule : undefined
}

function cleanTags(value: unknown): string[] | undefined {
    if (!Array.isArray(value) || !value.every((tag) => typeof tag === 'string')) {
        return undefined
    }
    // Normalized here rather than trusted: the tag editor writes normalized tags, so an
    // unnormalized one from a link would be an entry the user cannot reproduce by typing it.
    const tags = normalizeScoutTags(value as string[]).slice(0, MAX_SCOUT_TAGS)
    return tags.length > 0 ? tags : undefined
}

/** Keep the prefillable settings, dropping any field that isn't one or isn't in range. */
function cleanConfig(raw: unknown): ScoutTemplateConfig | null {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
        return null
    }
    const { run_interval_minutes, run_cron_schedule, emit, tags } = raw as Record<string, unknown>
    const config: ScoutTemplateConfig = {
        ...defined('run_interval_minutes', cleanInterval(run_interval_minutes)),
        ...defined('run_cron_schedule', cleanCron(run_cron_schedule)),
        ...defined('emit', typeof emit === 'boolean' ? emit : undefined),
        ...defined('tags', cleanTags(tags)),
    }
    return Object.keys(config).length > 0 ? config : null
}

/** The skill name a link asked for, prefixed if it needs it, or empty when it isn't usable. */
function cleanScoutName(value: unknown): string {
    const name = typeof value === 'string' ? value.trim() : ''
    if (!name) {
        return ''
    }
    const prefixed = name.startsWith(SIGNALS_SCOUT_SKILL_PREFIX) ? name : `${SIGNALS_SCOUT_SKILL_PREFIX}${name}`
    // Invalid name: drop it so the form's default prefix stands rather than the link failing.
    return validateSkillName(prefixed) ? '' : prefixed
}

/** The decoded payload object, or null when the value isn't one. */
function parsePayload(raw: unknown): Record<string, unknown> | null {
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
    return parsed as Record<string, unknown>
}

/** Decodes a `#createScout=` value into modal initial values. Null means ignore the fragment. */
export function decodeScoutCreateTemplate(raw: unknown): ScoutCreateInitialValues | null {
    const parsed = parsePayload(raw)
    if (!parsed) {
        return null
    }

    const { name, description, body, config } = parsed
    const cleanDescription =
        typeof description === 'string' ? description.trim().slice(0, SKILL_DESCRIPTION_MAX_LENGTH) : ''
    const cleanBody = typeof body === 'string' ? body.trim().slice(0, MAX_BODY_LENGTH) : ''

    // A link that prefills nothing but a name is indistinguishable from noise — require substance.
    if (!cleanDescription && !cleanBody) {
        return null
    }

    return {
        ...defined('name', cleanScoutName(name) || undefined),
        ...defined('description', cleanDescription || undefined),
        ...defined('body', cleanBody || undefined),
        ...defined('config', cleanConfig(config) ?? undefined),
    }
}
