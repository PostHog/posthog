import type { ToolHooks } from '@/tools/tool-hooks'

import { withConditionIds } from './conditionIds'

export default {
    afterResponse: (_context, _params, result) => withConditionIds(result),
} satisfies ToolHooks<unknown>
