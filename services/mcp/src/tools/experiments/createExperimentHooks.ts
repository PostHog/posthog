/** Hooks for the generated `experiment-create` tool. They move the variant detail inputs into `parameters`. */
import type { ToolHooks } from '@/tools/tool-hooks'

import { type VariantDetailParams, withVariantDetailsInParameters } from './variantDetails'

export default {
    transformBody: (_context, params, body) => withVariantDetailsInParameters(body, params, undefined),
} satisfies ToolHooks<VariantDetailParams>
