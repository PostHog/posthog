import type { z } from 'zod'

import { AnnotationCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = AnnotationCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const annotationResult = await context.api.annotations({ projectId }).create({ data })
    if (!annotationResult.success) {
        throw new Error(`Failed to create annotation: ${annotationResult.error.message}`)
    }

    return {
        ...annotationResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/annotations`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'annotation-create',
    schema,
    handler: createHandler,
})

export default tool
