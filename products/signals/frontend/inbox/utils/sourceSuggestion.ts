import { urls } from 'scenes/urls'

import type { SuggestedSourceProductEnumApi } from 'products/signals/frontend/generated/api.schemas'

/** The landing page a report's product suggestion sends the reader to, and the button that opens it. */
export const SOURCE_SUGGESTION_TARGETS: Record<
    SuggestedSourceProductEnumApi,
    { url: () => string; actionLabel: string }
> = {
    logs: { url: () => urls.logs(), actionLabel: 'Set up logs' },
    session_replay: { url: () => urls.replay(), actionLabel: 'Set up session replay' },
    error_tracking: { url: () => urls.errorTracking(), actionLabel: 'Set up error tracking' },
    llm_analytics: { url: () => urls.aiObservabilityDashboard(), actionLabel: 'Set up AI observability' },
}
