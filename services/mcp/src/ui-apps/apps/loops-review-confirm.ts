import type { LoopReviewData } from 'products/tasks/mcp/apps'

import { APP_DATA_META_KEY } from '../types'

// `loops-create` is a confirmed action (prepare/execute) and the card's click is the human
// confirmation step, so only fields the card renders may travel: anything else in `data`
// would be created without ever being reviewed. Keying off `LoopReviewData` makes the
// compiler reject a card field that isn't listed here.
const REVIEWED_FIELDS: Record<Exclude<keyof LoopReviewData, '_posthogUrl'>, true> = {
    name: true,
    description: true,
    instructions: true,
    runtime_adapter: true,
    model: true,
    reasoning_effort: true,
    visibility: true,
    repositories: true,
    triggers: true,
    enabled: true,
    overlap_policy: true,
    behaviors: true,
    connectors: true,
    sandbox_environment: true,
    notifications: true,
    context_target: true,
}

export function buildReviewedConfig(data: LoopReviewData): Record<string, unknown> {
    const reviewed: Record<string, unknown> = {}
    for (const key of Object.keys(REVIEWED_FIELDS)) {
        reviewed[key] = data[key as keyof LoopReviewData]
    }
    return reviewed
}

// `-prepare` tools have no UI resource, so the server mirrors the result onto the app-only
// `_meta` channel; `structuredContent` stays as a fallback for hosts that forward it.
export function extractConfirmationHash(prepared: {
    _meta?: Record<string, unknown>
    structuredContent?: unknown
}): string | undefined {
    const preparedData = (prepared._meta?.[APP_DATA_META_KEY] ?? prepared.structuredContent) as
        | { confirmation_hash?: unknown }
        | undefined
    const hash = preparedData?.confirmation_hash
    return typeof hash === 'string' && hash.length > 0 ? hash : undefined
}
