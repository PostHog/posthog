import type { z } from 'zod'

import { GenerateCanvasSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = GenerateCanvasSchema

type Params = z.infer<typeof schema>

type Result = {
    id: string
    name: string
    content: string
    task: string | null
    created_at: string
    updated_at: string
}

export const generateCanvasHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.canvases({ projectId }).generate({
        prompt: params.prompt,
        name: params.name,
        task: params.task,
    })

    if (!result.success) {
        throw new Error(`Failed to generate canvas: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'generate-canvas',
    schema,
    handler: generateCanvasHandler,
})

export default tool
