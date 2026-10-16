import { urls } from 'scenes/urls'

import type { SuggestedSourceProductEnumApi } from 'products/signals/frontend/generated/api.schemas'

export interface SourceSuggestionTarget {
    url: () => string
    actionLabel: string
}

/** The landing page a report's product suggestion sends the reader to, and the button that opens it. */
const SOURCE_SUGGESTION_TARGETS: Record<SuggestedSourceProductEnumApi, SourceSuggestionTarget> = {
    logs: { url: () => urls.logs(), actionLabel: 'Set up logs' },
    session_replay: { url: () => urls.replay(), actionLabel: 'Set up session replay' },
    error_tracking: { url: () => urls.errorTracking(), actionLabel: 'Set up error tracking' },
    llm_analytics: { url: () => urls.aiObservabilityDashboard(), actionLabel: 'Set up AI observability' },
}

/** Null for a product this build does not know yet, which a newer backend can send to a cached frontend. */
export function sourceSuggestionTarget(product: string): SourceSuggestionTarget | null {
    return Object.hasOwn(SOURCE_SUGGESTION_TARGETS, product)
        ? SOURCE_SUGGESTION_TARGETS[product as SuggestedSourceProductEnumApi]
        : null
}
