/**
 * Hooks for the generated `experiment-list` tool. They summarize which variants have notes or
 * screenshots, and add a `condition_id` to each condition of each linked flag.
 */
import { withConditionIds } from '@/tools/featureFlags/conditionIds'
import type { ToolHooks } from '@/tools/tool-hooks'

import { summarizeVariantDetails } from './variantDetails'

export default {
    afterResponse: (_context, _params, result) => {
        const page = result as { results?: { parameters?: unknown }[] }
        return withConditionIds({ ...page, results: (page.results ?? []).map(summarizeVariantDetails) })
    },
} satisfies ToolHooks<Record<string, unknown>>
