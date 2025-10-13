import { OrganizationGetDetailsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = OrganizationGetDetailsSchema

type Params = z.infer<typeof schema>

export const getDetailsHandler = async (context: Context, _params: Params) => {
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
        content: [{ type: 'text', text: JSON.stringify(orgResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'organization-details-get',
    schema,
    handler: getDetailsHandler,
})

export default tool
