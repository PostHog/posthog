/**
 * Withholds everything but the AI payload from `query-llm-trace` and
 * `query-llm-traces-list` responses.
 *
 * An event's `properties` bag is caller-controlled and open-ended: next to the
 * prompts and costs an agent asks for, it carries whatever the calling
 * application and its framework put there, including credentials and user
 * identity. A rule that names what to drop always trails the data, so this is
 * an allowlist. A withheld property is reported by name, so an agent can see
 * that it exists and read it in PostHog.
 *
 * This is a client-boundary safeguard on these two tools only. Stored events,
 * the PostHog UI, and property filters keep the complete bag, so a query can
 * still filter on a property it cannot read back.
 */

import { assignKey, isRecord } from '@/lib/plain-object'
import { AI_TAXONOMY_EVENT_PROPERTIES } from '@/lib/trace-property-allowlist.generated'

const RETAINED_AI_PROPERTIES = new Set<string>(AI_TAXONOMY_EVENT_PROPERTIES)

/**
 * `$ai_*` names first-party code writes that `taxonomy.py` does not describe, so
 * the generator cannot emit them. `$ai_generation_id` identifies a generation
 * node, which both tool descriptions promise. The LLM gateway writes the other
 * three onto generation events, and the personal-spend report reads the two
 * cache costs back, so withholding them would hide part of a trace's spend while
 * `$ai_total_cost_usd` still arrived. Each is a scalar or a short label.
 */
const RETAINED_UNDESCRIBED_AI_PROPERTIES = new Set([
    '$ai_generation_id',
    '$ai_cache_read_cost_usd',
    '$ai_cache_creation_cost_usd',
    '$ai_effort',
])

/** Non-`$ai_*` properties kept so a trace stays navigable and attributable. */
const RETAINED_NAVIGATION_PROPERTIES = new Set(['$session_id', '$lib', '$lib_version'])

/**
 * Endpoint properties kept without their query string. A provider URL routinely
 * carries the API key as a query parameter.
 */
const SANITIZED_URL_PROPERTIES = new Set(['$ai_base_url', '$ai_request_url'])

/**
 * Names of the properties withheld from a bag, reported in place of their
 * values. It sits beside `properties` rather than inside it, so it cannot
 * collide with a captured property of the same name.
 */
const REDACTED_KEYS_FIELD = '_redactedKeys'

/**
 * Reduce an endpoint property to its origin and path, or withhold it. Only an
 * absolute `http:` or `https:` URL has an origin and a path to keep. `URL`
 * accepts an opaque scheme too, and there the whole value sits in the path: a
 * `data:` URL parses, so `origin` is the string `"null"` and `pathname` is the
 * payload, credential and all. Anything else is withheld rather than guessed at.
 */
function sanitizeUrl(value: unknown): string | undefined {
    if (typeof value !== 'string') {
        return undefined
    }
    let url: URL
    try {
        url = new URL(value)
    } catch {
        return undefined
    }
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
        return undefined
    }
    return `${url.origin}${url.pathname}`
}

function isRetained(key: string): boolean {
    return (
        RETAINED_AI_PROPERTIES.has(key) ||
        RETAINED_UNDESCRIBED_AI_PROPERTIES.has(key) ||
        RETAINED_NAVIGATION_PROPERTIES.has(key)
    )
}

/**
 * Empty a property bag that is not a record. The filter decides key by key, so an
 * array or a string gives it no keys to decide on. Returning such a bag unchanged
 * would pass every value in it to the client, so it is emptied instead, and the
 * field itself is named as withheld.
 */
function emptiedBag(owner: Record<string, unknown>): Record<string, unknown> {
    return { ...owner, properties: {}, [REDACTED_KEYS_FIELD]: ['properties'] }
}

/**
 * Filter an event property bag. Returns the event unchanged when the bag holds
 * nothing to withhold or sanitize, which is the common shape of an SDK trace.
 */
function redactEventBag(event: Record<string, unknown>): Record<string, unknown> {
    if (!('properties' in event)) {
        return event
    }
    const properties = event.properties
    if (!isRecord(properties)) {
        return emptiedBag(event)
    }
    const keys = Object.keys(properties)
    if (keys.every((key) => isRetained(key) && !SANITIZED_URL_PROPERTIES.has(key))) {
        return event
    }
    const retained: Record<string, unknown> = {}
    const withheld: string[] = []
    for (const key of keys) {
        if (SANITIZED_URL_PROPERTIES.has(key)) {
            const sanitized = sanitizeUrl(properties[key])
            if (sanitized === undefined) {
                withheld.push(key)
            } else {
                assignKey(retained, key, sanitized)
            }
        } else if (isRetained(key)) {
            assignKey(retained, key, properties[key])
        } else {
            withheld.push(key)
        }
    }
    return {
        ...event,
        properties: retained,
        ...(withheld.length > 0 ? { [REDACTED_KEYS_FIELD]: withheld } : {}),
    }
}

/**
 * Withhold every person property value. The allowlist above describes an AI
 * event, and a person bag is not one: its names come from `$set`, so a person
 * carrying `$ai_model` carries whatever the application chose to write there.
 * `uuid` and `distinct_id` sit outside the bag, so the person stays navigable.
 */
function redactPersonBag(person: Record<string, unknown>): Record<string, unknown> {
    if (!('properties' in person)) {
        return person
    }
    const properties = person.properties
    if (!isRecord(properties)) {
        return emptiedBag(person)
    }
    const withheld = Object.keys(properties)
    if (withheld.length === 0) {
        return person
    }
    return { ...person, properties: {}, [REDACTED_KEYS_FIELD]: withheld }
}

/** Redact one trace: every event bag, and the person bag attached to the trace. */
export function redactTrace(trace: unknown): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    const out: Record<string, unknown> = { ...trace }
    if (Array.isArray(trace.events)) {
        out.events = trace.events.map((event) => (isRecord(event) ? redactEventBag(event) : event))
    }
    if (isRecord(trace.person)) {
        out.person = redactPersonBag(trace.person)
    }
    return out
}

/** Redact the `results` array of a trace query, before it is compacted. */
export function redactTraceResults(results: unknown): unknown {
    return Array.isArray(results) ? results.map(redactTrace) : results
}
