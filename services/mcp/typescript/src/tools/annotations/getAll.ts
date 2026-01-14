import type { z } from 'zod'

import { AnnotationGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = AnnotationGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const annotationsResult = await context.api.annotations({ projectId }).list({ params: data ?? {} })
    if (!annotationsResult.success) {
        throw new Error(`Failed to get annotations: ${annotationsResult.error.message}`)
    }

    return annotationsResult.data.map((annotation) => ({
        ...annotation,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/annotations/${annotation.id}`,
    }))
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'annotation-list',
    schema,
    handler: getAllHandler,
})

export default tool
