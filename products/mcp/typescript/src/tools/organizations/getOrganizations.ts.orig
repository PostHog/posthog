import { OrganizationGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
<<<<<<< LEFT
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
||||||| BASE
import type { z } from 'zod'
=======
>>>>>>> RIGHT

const schema = OrganizationGetAllSchema

export const getOrganizationsHandler: ToolBase<typeof schema>['handler'] = async (context: Context) => {
    const orgsResult = await context.api.organizations().list()
    if (!orgsResult.success) {
        throw new Error(`Failed to get organizations: ${orgsResult.error.message}`)
    }

    return {
        content: [{ type: 'text', text: formatResponse(orgsResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'organizations-get',
    schema,
    handler: getOrganizationsHandler,
})

export default tool
