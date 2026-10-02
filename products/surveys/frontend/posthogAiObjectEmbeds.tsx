import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'

const SurveyObjectEmbed = lazyWithRetry(() =>
    import('./posthogAi/SurveyObjectEmbed').then((m) => ({ default: m.SurveyObjectEmbed }))
)

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [{ kind: 'survey', Embed: SurveyObjectEmbed }]
