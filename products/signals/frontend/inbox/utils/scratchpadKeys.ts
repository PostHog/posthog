import { type ComponentProps } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

type LemonTagType = ComponentProps<typeof LemonTag>['type']

/**
 * The key prefix (everything before the first colon) encodes the note's *kind* — what the scout
 * was doing when it wrote it. This map doubles as the roster of kinds the fleet actually uses: a
 * key whose prefix is absent here is treated as a topic, not a kind, so one-off namespaces do not
 * turn into ledger kinds.
 */
export const KIND_TAG_TYPE: Record<string, LemonTagType> = {
    // Durable knowledge: what the fleet has worked out and trusts.
    pattern: 'highlight',
    baseline: 'success',
    noise: 'muted',
    allowlist: 'muted',
    'not-in-use': 'muted',
    coverage: 'completion',
    taxonomy: 'option',
    tags: 'option',
    watch: 'warning',
    watchlist: 'warning',
    emerging: 'primary',
    explore: 'option',
    recheck: 'caution',
    finding: 'primary',
    improve: 'caution',
    'mcp-gap': 'caution',
    // Bookkeeping: what keeps a scout from repeating itself.
    dedupe: 'muted',
    judged: 'muted',
    report: 'muted',
    reported: 'muted',
    reviewer: 'muted',
    followup: 'muted',
    cursor: 'muted',
    snapshot: 'muted',
    skip: 'muted',
    covered: 'muted',
    pending: 'muted',
    addressed: 'muted',
    already_addressed: 'muted',
    disqualified: 'muted',
}

/**
 * Kinds a scout writes for itself rather than for a reader: which signals it has already judged,
 * which reports it has filed, where its last sweep stopped. They dominate the window by volume,
 * so the panel can drop them in one switch and leave the durable knowledge behind.
 */
export const BOOKKEEPING_KINDS = new Set([
    'dedupe',
    'judged',
    'report',
    'followup',
    'cursor',
    'snapshot',
    'already_addressed',
    'addressed',
    'covered',
    'pending',
])

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Whether a key segment is a report UUID, which the ledger resolves to that report's title. */
export function isReportUuid(segment: string): boolean {
    return UUID_PATTERN.test(segment)
}

/** The note's kind, or null when the key's first segment is not one the fleet uses as a kind. */
export function scratchpadKindOf(key: string): string | null {
    const [first] = key.split(':')
    return first && first !== key && first in KIND_TAG_TYPE ? first : null
}

/**
 * What the note is about. A kind-prefixed key carries its topic in the second segment
 * (`pattern:apm:p95-window` is about `apm`); a key with no recognized kind is its own topic
 * (`billing_spikes:34316` is about `billing_spikes`).
 */
export function scratchpadTopicOf(key: string): string | null {
    const segments = key.split(':')
    const topic = scratchpadKindOf(key) ? segments[1] : segments[0]
    return topic || null
}
