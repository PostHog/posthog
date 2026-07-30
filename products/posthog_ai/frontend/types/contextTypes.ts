/**
 * Abstract, domain-agnostic attached-context shape for the PostHog AI surface. The surface never
 * enumerates entity types — a provider names an arbitrary `type` (e.g. 'insight', 'dashboard',
 * 'trace', 'text') and the block builder renders it as-is.
 */
export interface AttachedContextItem {
    /** Arbitrary resource kind, e.g. 'insight', 'dashboard', 'trace', 'text'. */
    type: string
    /** Resource identifier — entity id, short_id, $ai_trace_id, … */
    key?: string | number
    /** Optional human-readable label. */
    label?: string
    /** Free-text payload (used when there's no keyed resource, e.g. type 'text'). */
    value?: string
}

/** Stable dedupe key for an attached context item: `${type}:${key ?? value}`. */
export function attachedContextItemKey(item: AttachedContextItem): string {
    return `${item.type}:${item.key ?? item.value ?? ''}`
}
