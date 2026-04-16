import type { z } from 'zod'

import { isValidOrganizationId } from '@/lib/validation'
import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = OrganizationSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

export const setActiveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { orgId } = params
    // The cached orgId is interpolated into PostHog API URL paths, so any
    // value the model can supply has to match the documented UUID shape.
    if (!isValidOrganizationId(orgId)) {
        return {
            content: [
                {
                    type: 'text',
                    text: `Invalid organization ID format: ${JSON.stringify(orgId)}`,
                },
            ],
        }
    }
    await context.cache.set('orgId', orgId)
    await context.stateManager.invalidateAiConsent()

    return {
        content: [{ type: 'text', text: `Switched to organization ${orgId}` }],
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'switch-organization',
    schema,
    handler: setActiveHandler,
})

export default tool
