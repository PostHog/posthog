import { identifierToHuman } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { INBOX_SOURCE_OPTIONS } from '../filterOptions'
import { safeHttpUrl } from './reportPresentation'

/**
 * Deep link into the PostHog product an entity came from, or null when the product has no entity
 * page or the entity id is missing. `logs` has no per-entity page, so it links to the logs scene.
 */
export function signalEntityUrl(sourceProduct: string, entityId?: string | null): string | null {
    switch (sourceProduct) {
        case 'error_tracking':
            return entityId ? urls.errorTrackingIssue(entityId) : null
        case 'session_replay':
            return entityId ? urls.replaySingle(entityId) : null
        case 'llm_analytics':
            return entityId ? urls.aiObservabilityTrace(entityId) : null
        case 'logs':
            return urls.logs()
        default:
            return null
    }
}

const ENTITY_LINK_LABELS: Record<string, string> = {
    error_tracking: 'View issue',
    session_replay: 'View replay',
    llm_analytics: 'View trace',
    logs: 'View logs',
}

/** Keys emitters use for the object's own web address, in preference order. */
const EXTRA_URL_KEYS = ['html_url', 'url', 'web_url', 'permalink', 'link'] as const

export interface SignalLink {
    to: string
    label: string
    /** True for a link that leaves PostHog, so callers open it in a new tab. */
    external: boolean
}

function sourceProductLabel(sourceProduct: string): string {
    return (
        INBOX_SOURCE_OPTIONS.find((option) => option.value === sourceProduct)?.label ?? identifierToHuman(sourceProduct)
    )
}

/**
 * Best available link for a signal that has no dedicated card, or whose `extra` doesn't satisfy
 * that card's guard: a PostHog entity page from `(source_product, source_id)` first, then an
 * http(s) URL the emitter put on `extra`. Relative paths on `extra` are ignored because, without
 * a product to anchor them, there is no way to tell a real route from an emitter's internal key.
 */
export function genericSignalLink(signal: {
    source_product: string
    source_id: string
    extra: unknown
}): SignalLink | null {
    const entityUrl = signalEntityUrl(signal.source_product, signal.source_id)
    if (entityUrl) {
        return { to: entityUrl, label: ENTITY_LINK_LABELS[signal.source_product] ?? 'View', external: false }
    }
    const extra =
        typeof signal.extra === 'object' && signal.extra !== null ? (signal.extra as Record<string, unknown>) : {}
    for (const key of EXTRA_URL_KEYS) {
        const candidate = extra[key]
        const url = typeof candidate === 'string' ? safeHttpUrl(candidate) : null
        if (url) {
            return { to: url, label: `View in ${sourceProductLabel(signal.source_product)}`, external: true }
        }
    }
    return null
}
