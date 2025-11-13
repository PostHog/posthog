import { OrganizationGetDetailsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
<<<<<<< LEFT
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
||||||| BASE
import type { z } from 'zod'
=======
>>>>>>> RIGHT

const schema = OrganizationGetDetailsSchema

export const getDetailsHandler: ToolBase<typeof schema>['handler'] = async (context: Context) => {
    const orgId = await context.stateManager.getOrgID()

    if (!orgId) {
        throw new Error(
            'API key does not have access to any organizations. This is likely because the API key is scoped to a project, and not an organization.'
        )
    }

    const orgResult = await context.api.organizations().get({ orgId })

    if (!orgResult.success) {
        throw new Error(`Failed to get organization details: ${orgResult.error.message}`)
    }

    return {
        content: [{ type: 'text', text: formatResponse(orgResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'organization-details-get',
    schema,
    handler: getDetailsHandler,
})

export default tool
