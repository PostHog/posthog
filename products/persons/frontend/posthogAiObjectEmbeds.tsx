import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ObjectEmbedEntry } from 'products/posthog_ai/frontend/api/types'

const PersonObjectEmbed = lazyWithRetry(() =>
    import('./posthogAi/PersonObjectEmbed').then((m) => ({ default: m.PersonObjectEmbed }))
)

export const posthogAiObjectEmbeds: ObjectEmbedEntry[] = [{ kind: 'person', Embed: PersonObjectEmbed }]
