import type { z } from 'zod'

import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = OrganizationSetActiveSchema

type Params = z.infer<typeof schema>

export const setActiveHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { orgId } = params
    await context.cache.set('orgId', orgId)
    // Clear projectId when switching orgs - the cached project likely belongs to the old org
    // and would cause setDefaultOrganizationAndProject() to overwrite the org context
    await context.cache.delete('projectId')

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
