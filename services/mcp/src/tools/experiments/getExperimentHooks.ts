/** Hooks for the generated `experiment-get` tool. They add viewable URLs for the variant screenshots. */
import type { ToolHooks } from '@/tools/tool-hooks'

import { withVariantScreenshotUrls } from './variantDetails'

export default {
    afterResponse: (context, _params, result) =>
        withVariantScreenshotUrls(result as { parameters?: unknown }, context.api.publicBaseUrl),
} satisfies ToolHooks<Record<string, unknown>>
