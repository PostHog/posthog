import type { z } from 'zod'

import { ProjectSetActiveSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectSetActiveSchema

type Params = z.infer<typeof schema>

export const setActiveHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { projectId } = params

    await context.cache.set('projectId', projectId.toString())

    return {
        content: [{ type: 'text', text: `Switched to project ${projectId}` }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'switch-project',
    schema,
    handler: setActiveHandler,
})

export default tool
