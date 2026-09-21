/**
 * Filters LLM trace properties before they reach the MCP client. Next to the AI
 * payload, an event's `properties` bag can hold the credential, the authentication
 * state, request headers, identity, permissions, and location behind the call, and
 * that half of the bag is caller-controlled, so the filter keeps a known namespace
 * instead of naming what to drop. It stays a pass of its own rather than folding
 * into the compaction walk, so a compaction bug cannot become a disclosure.
 */

import { assignKey, isRecord } from '@/lib/trace-compaction'

const ALLOWED_KEY_PREFIX = '$ai_'

// Kept by name: the session link and the sending SDK, which an agent acts on.
const ALLOWED_KEYS = new Set(['$session_id', '$lib', '$lib_version'])

// A copy of the raw bag, taken before ingestion strips the caller's identity fields.
const RAW_EVENT_SNAPSHOT_KEY = '$ai_debug_data'

// A provider that authenticates by query parameter puts the key inside the URL.
const URL_PROPERTIES = new Set(['$ai_request_url', '$ai_base_url'])

const REDACTION_REASON =
    'Each `_redactedKeys` list names properties this response withholds, because they can carry authentication state, credentials, request headers, user identity, permissions, location, or budget context.'
const REDACTION_NOTE =
    'The values are unchanged in PostHog. Open the trace there, or query the one property you need, if a diagnosis depends on it.'

function isAllowed(key: string): boolean {
    return key.startsWith(ALLOWED_KEY_PREFIX) || ALLOWED_KEYS.has(key)
}

function endpointOnly(value: unknown): string | undefined {
    if (typeof value !== 'string') {
        return undefined
    }
    let url: URL
    try {
        url = new URL(value)
    } catch {
        return undefined
    }
    const endpoint = `${url.origin}${url.pathname}`
    const carriedSecrets = url.username || url.password || url.search || url.hash
    return carriedSecrets ? `${endpoint} [userinfo and query stripped]` : endpoint
}

export interface RedactedTraceResults {
    results: unknown
    notice?: { reason: string; note: string }
}

export function redactTraceResults(results: unknown): RedactedTraceResults {
    if (!Array.isArray(results)) {
        return { results }
    }
    let withheldAny = false

    function redactProperties(properties: unknown): unknown {
        if (!isRecord(properties)) {
            return properties
        }
        const kept: Record<string, unknown> = {}
        const withheld: string[] = []
        for (const [key, value] of Object.entries(properties)) {
            if (!isAllowed(key)) {
                withheld.push(key)
                continue
            }
            if (key === RAW_EVENT_SNAPSHOT_KEY) {
                assignKey(kept, key, redactProperties(value))
                continue
            }
            if (URL_PROPERTIES.has(key)) {
                const endpoint = endpointOnly(value)
                if (endpoint === undefined) {
                    withheld.push(key)
                    continue
                }
                assignKey(kept, key, endpoint)
                continue
            }
            assignKey(kept, key, value)
        }
        if (withheld.length === 0) {
            return kept
        }
        withheldAny = true
        // First, not last: the compactor fills a bag in insertion order and stops when
        // the budget runs out, so a trailing `_redactedKeys` can be the entry it drops.
        return { _redactedKeys: withheld, ...kept }
    }

    function redactBag(owner: Record<string, unknown>): Record<string, unknown> {
        if (!('properties' in owner)) {
            return owner
        }
        return { ...owner, properties: redactProperties(owner.properties) }
    }

    function redactTrace(trace: unknown): unknown {
        if (!isRecord(trace)) {
            return trace
        }
        const out = { ...trace }
        if (Array.isArray(out.events)) {
            out.events = out.events.map((event) => (isRecord(event) ? redactBag(event) : event))
        }
        if (isRecord(out.person)) {
            out.person = redactBag(out.person)
        }
        return out
    }

    const redacted = results.map(redactTrace)
    // One notice per response: repeating it per trace would spend the list budget.
    return {
        results: redacted,
        ...(withheldAny ? { notice: { reason: REDACTION_REASON, note: REDACTION_NOTE } } : {}),
    }
}
