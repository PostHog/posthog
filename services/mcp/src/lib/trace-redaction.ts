/**
 * Filters LLM trace properties before they reach the MCP client. A trace event
 * carries its whole `properties` bag, which holds the authentication method
 * behind the call, credential and session handles, the caller's identity,
 * permissions, and approximate location next to the AI payload. That half of the
 * bag is caller-controlled, so the filter keeps a known namespace rather than
 * naming what to drop. The stored event and the PostHog UI are unaffected.
 */

const ALLOWED_KEY_PREFIX = '$ai_'

// Kept by name because the namespace rule would drop them. `$session_id` links a
// trace to its session recording, and the library pair identifies the sending SDK.
const ALLOWED_KEYS = new Set(['$session_id', '$lib', '$lib_version'])

const REDACTION_REASON =
    'Properties outside the $ai_* namespace are withheld from MCP responses, because they can carry authentication state, credentials, request headers, user identity, permissions, location, or budget context.'
const REDACTION_NOTE =
    'The values are unchanged in PostHog. Open the trace there, or query the one property you need, if a diagnosis depends on it.'

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isAllowed(key: string): boolean {
    return key.startsWith(ALLOWED_KEY_PREFIX) || ALLOWED_KEYS.has(key)
}

function redactProperties(properties: unknown): unknown {
    if (!isRecord(properties)) {
        return properties
    }
    const kept: Record<string, unknown> = {}
    const withheld: string[] = []
    for (const [key, value] of Object.entries(properties)) {
        if (isAllowed(key)) {
            // `__proto__` fails `isAllowed`, so this assignment cannot reach the
            // inherited setter the way an unfiltered copy would.
            kept[key] = value
        } else {
            withheld.push(key)
        }
    }
    if (withheld.length > 0) {
        kept._redacted = { withheldKeys: withheld, reason: REDACTION_REASON, note: REDACTION_NOTE }
    }
    return kept
}

function redactEvent(event: unknown): unknown {
    if (!isRecord(event) || !('properties' in event)) {
        return event
    }
    return { ...event, properties: redactProperties(event.properties) }
}

function redactTrace(trace: unknown): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    const out = { ...trace }
    if (Array.isArray(out.events)) {
        out.events = out.events.map(redactEvent)
    }
    // A trace can carry the person behind it, whose properties are identity metadata.
    if (isRecord(out.person) && 'properties' in out.person) {
        out.person = { ...out.person, properties: redactProperties(out.person.properties) }
    }
    return out
}

export function redactTraceResults(results: unknown): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    return results.map(redactTrace)
}
