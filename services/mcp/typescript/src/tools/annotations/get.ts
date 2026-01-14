import type { z } from 'zod'

import { AnnotationGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = AnnotationGetSchema

type Params = z.infer<typeof schema>

export const getHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { annotationId } = params
    const projectId = await context.stateManager.getProjectId()
    const annotationResult = await context.api.annotations({ projectId }).get({ annotationId })
    if (!annotationResult.success) {
        throw new Error(`Failed to get annotation: ${annotationResult.error.message}`)
    }

    return {
        ...annotationResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/annotations/${annotationResult.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'annotation-get',
    schema,
    handler: getHandler,
})

export default tool
