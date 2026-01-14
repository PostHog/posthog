import type { z } from 'zod'

import { AnnotationUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = AnnotationUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { annotationId, data } = params
    const projectId = await context.stateManager.getProjectId()
    const annotationResult = await context.api.annotations({ projectId }).update({ annotationId, data })
    if (!annotationResult.success) {
        throw new Error(`Failed to update annotation: ${annotationResult.error.message}`)
    }

    return {
        ...annotationResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/annotations`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'annotation-update',
    schema,
    handler: updateHandler,
})

export default tool
