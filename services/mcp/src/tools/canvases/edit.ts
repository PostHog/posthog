import type { z } from 'zod'

import { EditCanvasSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EditCanvasSchema

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

export const editCanvasHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.canvases({ projectId }).update({
        id: params.id,
        name: params.name,
        content: params.content,
        path: params.path,
        task: params.task,
    })

    if (!result.success) {
        throw new Error(`Failed to edit canvas: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'edit-canvas',
    schema,
    handler: editCanvasHandler,
})

export default tool
