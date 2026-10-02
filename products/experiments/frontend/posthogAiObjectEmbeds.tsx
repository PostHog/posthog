import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'

const ExperimentObjectEmbed = lazyWithRetry(() =>
    import('./posthogAi/ExperimentObjectEmbed').then((m) => ({ default: m.ExperimentObjectEmbed }))
)

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [{ kind: 'experiment', Embed: ExperimentObjectEmbed }]
