/** Hooks for the generated `experiment-list` tool. They summarize which variants have notes or screenshots. */
import type { ToolHooks } from '@/tools/tool-hooks'

import { summarizeVariantDetails } from './variantDetails'

export default {
    afterResponse: (_context, _params, result) => {
        const page = result as { results?: { parameters?: unknown }[] }
        return { ...page, results: (page.results ?? []).map(summarizeVariantDetails) }
    },
} satisfies ToolHooks<Record<string, unknown>>
