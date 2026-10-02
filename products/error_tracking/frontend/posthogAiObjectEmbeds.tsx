import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'

const ErrorTrackingIssueObjectEmbed = lazyWithRetry(() =>
    import('./posthogAi/ErrorTrackingIssueObjectEmbed').then((m) => ({ default: m.ErrorTrackingIssueObjectEmbed }))
)

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [{ kind: 'error', Embed: ErrorTrackingIssueObjectEmbed }]
