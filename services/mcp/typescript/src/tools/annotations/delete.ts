import type { z } from 'zod'

import { AnnotationDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = AnnotationDeleteSchema

type Params = z.infer<typeof schema>

export const deleteHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { annotationId } = params
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.annotations({ projectId }).delete({ annotationId })
    if (!result.success) {
        throw new Error(`Failed to delete annotation: ${result.error.message}`)
    }
    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'annotation-delete',
    schema,
    handler: deleteHandler,
})

export default tool
