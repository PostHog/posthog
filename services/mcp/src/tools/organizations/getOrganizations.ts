import type { Schemas } from '@/api/generated'
import { wrapError } from '@/lib/errors'
import { OrganizationGetAllSchema } from '@/schema/tool-inputs'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = OrganizationGetAllSchema

// Mirror the allowlist the generated `organizations-list` tool applies. The
// `/api/organizations/` rows are serialized by the full `OrganizationSerializer`
// (billing `customer_id`, `available_product_features`, 2FA/AI/security
// settings, nested teams/projects, ...), so returning them verbatim would
// broaden what workspace clients receive well beyond the id/name/membership
// data this discovery tool advertises.
const ORGANIZATION_FIELDS = ['id', 'name', 'slug', 'membership_level']

export const getOrganizationsHandler: ToolBase<typeof schema, Partial<Schemas.OrganizationBasic>[]>['handler'] = async (
    context: Context
) => {
    const orgsResult = await context.api.organizations().list()

    if (!orgsResult.success) {
        // Preserve the typed API error as `cause` so `handleToolError` can still
        // classify a recoverable 4xx and keep it out of exception tracking.
        throw wrapError(`Failed to get organizations: ${orgsResult.error.message}`, orgsResult.error)
    }

    return orgsResult.data.map((org: Schemas.OrganizationBasic) => pickResponseFields(org, ORGANIZATION_FIELDS))
}

const tool = (): ToolBase<typeof schema, Partial<Schemas.OrganizationBasic>[]> => ({
    name: 'organizations-get',
    schema,
    handler: getOrganizationsHandler,
})

export default tool
