import type { z } from 'zod'

import { LoopsCreateBody } from '@/generated/tasks/api'
import { withUiApp } from '@/resources/ui-apps'
import type { Context, ToolBase } from '@/tools/types'

// The review card's input is exactly the `loops-create` body, so the card's "Create loop"
// button can forward the reviewed config unchanged. This tool doesn't write anything — it
// echoes the config back so the UI app can render it for confirmation.
const schema = LoopsCreateBody

type Params = z.infer<typeof schema>

export const loopsReviewHandler: ToolBase<typeof schema, Params>['handler'] = async (
    _context: Context,
    params: Params
) => params

export default (): ToolBase<typeof schema, Params> =>
    withUiApp('loops-review', {
        name: 'loops-review',
        schema,
        handler: loopsReviewHandler,
    })
