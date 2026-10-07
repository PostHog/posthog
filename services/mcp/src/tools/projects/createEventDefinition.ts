import type { z } from 'zod'

import { wrapError } from '@/lib/errors'
import type { ApiEventDefinition } from '@/schema/api'
import { EventDefinitionCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = EventDefinitionCreateSchema

type Params = z.infer<typeof schema>

type Result = ApiEventDefinition & { url: string }

export const createEventDefinitionHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.projects().createEventDefinition({
        projectId,
        eventName: params.eventName,
        data: params.data,
    })

    if (!result.success) {
        // Preserve the typed API error as `cause` so `handleToolError` can
        // classify a recoverable failure instead of counting it as an internal
        // fault. A duplicate name is handled upstream as an idempotent update,
        // so a failure here is a genuine rejection (bad metadata, missing scope).
        throw wrapError(`Failed to create event definition: ${result.error.message}`, result.error)
    }

    return {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/events/${encodeURIComponent(result.data.id)}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'event-definition-create',
    schema,
    handler: createEventDefinitionHandler,
})

export default tool
