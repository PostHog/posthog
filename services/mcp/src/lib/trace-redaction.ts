/**
 * Bounds what an LLM trace discloses before it is serialized toward the MCP
 * client. Trace events carry their whole `properties` bag, which holds far more
 * than the AI payload: the authentication method behind the call, credential and
 * session handles, the caller's identity, permission and organization context,
 * request metadata, and approximate location. An agent inspecting a trace needs
 * none of that, so the bag is filtered down to the AI namespace instead of being
 * passed through.
 *
 * Redaction is a client-boundary safeguard only — the stored event and the
 * PostHog UI still hold every property. Filtered keys are reported by name, with
 * no value, so an agent can see that a property exists and go get it through a
 * path the person authorized on purpose.
 */

/** Property namespace the AI observability tools exist to return. */
const ALLOWED_KEY_PREFIX = '$ai_'

/**
 * General context an agent needs to act on a trace, kept by name because the
 * namespace rule alone would drop them. `$session_id` links a trace to its
 * session recording; the library pair identifies the SDK that sent the event.
 */
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

/**
 * Keep the allowed properties of one `properties` bag and list the names of the
 * rest under `_redacted`.
 */
function redactProperties(properties: unknown): unknown {
    if (!isRecord(properties)) {
        return properties
    }
    const kept: Record<string, unknown> = {}
    const withheld: string[] = []
    for (const [key, value] of Object.entries(properties)) {
        if (isAllowed(key)) {
            // `__proto__` fails `isAllowed`, so a plain assignment here cannot
            // walk into the inherited setter the way an unfiltered copy would.
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
    // A trace can carry the person behind it, whose properties are the identity
    // metadata the AI tools have no reason to hand an agent.
    if (isRecord(out.person) && 'properties' in out.person) {
        out.person = { ...out.person, properties: redactProperties(out.person.properties) }
    }
    return out
}

/** Redact the `results` array of a `TraceQuery` or `TracesQuery` response. */
export function redactTraceResults(results: unknown): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    return results.map(redactTrace)
}
