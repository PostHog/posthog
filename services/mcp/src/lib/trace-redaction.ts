/**
 * Filters LLM trace properties before they reach the MCP client. A trace event
 * carries its whole `properties` bag, which holds the authentication method
 * behind the call, credential and session handles, forwarded request headers,
 * the caller's identity, permissions, budget context, and approximate location
 * next to the AI payload. That half of the bag is caller-controlled, so the
 * filter keeps a known namespace instead of naming what to drop. The stored
 * event, the PostHog UI, and property filters are unaffected.
 */

const ALLOWED_KEY_PREFIX = '$ai_'

// Kept by name because the namespace rule would drop them. `$session_id` links a
// trace to its session recording, and the library pair identifies the sending SDK.
const ALLOWED_KEYS = new Set(['$session_id', '$lib', '$lib_version'])

const REDACTION_REASON =
    'Each `_redactedKeys` list names properties this response withholds, because they can carry authentication state, credentials, request headers, user identity, permissions, location, or budget context.'
const REDACTION_NOTE =
    'The values are unchanged in PostHog. Open the trace there, or query the one property you need, if a diagnosis depends on it.'

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isAllowed(key: string): boolean {
    return key.startsWith(ALLOWED_KEY_PREFIX) || ALLOWED_KEYS.has(key)
}

interface RedactionState {
    withheldAny: boolean
}

function redactProperties(properties: unknown, state: RedactionState): unknown {
    if (!isRecord(properties)) {
        return properties
    }
    const kept: Record<string, unknown> = {}
    const withheld: string[] = []
    for (const [key, value] of Object.entries(properties)) {
        if (isAllowed(key)) {
            // `__proto__` fails `isAllowed`, so this cannot reach the inherited setter.
            kept[key] = value
        } else {
            withheld.push(key)
        }
    }
    if (withheld.length > 0) {
        kept._redactedKeys = withheld
        state.withheldAny = true
    }
    return kept
}

function redactBag(owner: Record<string, unknown>, state: RedactionState): Record<string, unknown> {
    if (!('properties' in owner)) {
        return owner
    }
    return { ...owner, properties: redactProperties(owner.properties, state) }
}

function redactTrace(trace: unknown): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    const out = { ...trace }
    const state: RedactionState = { withheldAny: false }
    if (Array.isArray(out.events)) {
        out.events = out.events.map((event) => (isRecord(event) ? redactBag(event, state) : event))
    }
    if (isRecord(out.person)) {
        out.person = redactBag(out.person, state)
    }
    if (state.withheldAny) {
        // Once per trace, not once per bag: a trace holds hundreds of bags, and
        // repeating the explanation would spend the compaction budget on boilerplate.
        out._redacted = { reason: REDACTION_REASON, note: REDACTION_NOTE }
    }
    return out
}

export function redactTraceResults(results: unknown): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    return results.map(redactTrace)
}
