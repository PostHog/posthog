/**
 * Hooks for the generated `experiment-get` tool. They add viewable URLs for the variant screenshots
 * and a `condition_id` to each condition of the linked flag.
 */
import { withConditionIds } from '@/tools/featureFlags/conditionIds'
import type { ToolHooks } from '@/tools/tool-hooks'

import { withVariantScreenshotUrls } from './variantDetails'

export default {
    afterResponse: (context, _params, result) =>
        withConditionIds(withVariantScreenshotUrls(result as { parameters?: unknown }, context.api.publicBaseUrl)),
} satisfies ToolHooks<Record<string, unknown>>
