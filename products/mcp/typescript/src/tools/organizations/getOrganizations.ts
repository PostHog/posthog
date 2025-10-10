import { OrganizationGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = OrganizationGetAllSchema

type Params = z.infer<typeof schema>

export const getOrganizationsHandler = async (context: Context, _params: Params) => {
    const orgsResult = await context.api.organizations().list()
    if (!orgsResult.success) {
        throw new Error(`Failed to get organizations: ${orgsResult.error.message}`)
    }

    return {
        content: [{ type: 'text', text: JSON.stringify(orgsResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'organizations-get',
    schema,
    handler: getOrganizationsHandler,
})

export default tool
