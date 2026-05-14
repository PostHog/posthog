import type { z } from 'zod'

import { GetCanvasSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = GetCanvasSchema

type Params = z.infer<typeof schema>

type Result = {
    id: string
    name: string
    content: string
    path: string
    task: string | null
    created_at: string
    updated_at: string
}

export const getCanvasHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.canvases({ projectId }).get({ id: params.id })

    if (!result.success) {
        throw new Error(`Failed to fetch canvas: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'get-canvas',
    schema,
    handler: getCanvasHandler,
})

export default tool
