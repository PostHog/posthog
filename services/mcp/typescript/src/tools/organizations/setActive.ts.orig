import type { z } from 'zod'

import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = OrganizationSetActiveSchema

type Params = z.infer<typeof schema>

export const setActiveHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { orgId } = params
    await context.cache.set('orgId', orgId)

    return {
        content: [{ type: 'text', text: `Switched to organization ${orgId}` }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'switch-organization',
    schema,
    handler: setActiveHandler,
})

export default tool
