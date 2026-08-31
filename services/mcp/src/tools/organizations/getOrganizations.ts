import type { Schemas } from '@/api/generated'
import { PostHogApiError, wrapError } from '@/lib/errors'
import { OrganizationGetAllSchema } from '@/schema/tool-inputs'
import { pickResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = OrganizationGetAllSchema

// Returned to the agent when `/api/organizations/` responds 404. The list is
// available to every authenticated session, so a 404 is never transient: it
// means the request did not reach a PostHog account for these credentials,
// most often because the connection targets the wrong region. Agents read the
// bare `HTTP 404` status as a possible blip and retry the same call many times
// over (the dominant source of this tool's failure volume), so name the cause
// and tell them to stop instead.
const ORGANIZATIONS_NOT_FOUND_MESSAGE = [
    'The PostHog API returned 404 for the organizations list. This is not a transient error, and retrying this call returns 404 again.',
    '',
    'The organizations list is available to every valid session, so a 404 means this MCP connection did not reach a PostHog account for your credentials. The most common cause is a region mismatch, where the connection uses the US API with EU credentials or the EU API with US credentials.',
    '',
    'To fix this:',
    '1. Check whether your PostHog data is in the US or EU region.',
    '2. Reconnect the PostHog MCP for that region, or verify that your API key or OAuth connection is still valid.',
    '',
    'Do not retry this call until the connection is fixed.',
].join('\n')

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
        const { error } = orgsResult
        // Keep the 404 classified as a recoverable 4xx (so it stays out of
        // exception tracking and the telemetry summary is unchanged), but swap the
        // bare status for a message that names the cause and stops the retry loop.
        if (error instanceof PostHogApiError && error.status === 404) {
            throw new PostHogApiError({
                status: error.status,
                statusText: error.statusText,
                body: error.body,
                url: error.url,
                method: error.method,
                message: ORGANIZATIONS_NOT_FOUND_MESSAGE,
            })
        }
        // Preserve the typed API error as `cause` so `handleToolError` can still
        // classify a recoverable 4xx and keep it out of exception tracking.
        throw wrapError(`Failed to get organizations: ${error.message}`, error)
    }

    return orgsResult.data.map((org: Schemas.OrganizationBasic) => pickResponseFields(org, ORGANIZATION_FIELDS))
}

const tool = (): ToolBase<typeof schema, Partial<Schemas.OrganizationBasic>[]> => ({
    name: 'organizations-get',
    schema,
    handler: getOrganizationsHandler,
})

export default tool
