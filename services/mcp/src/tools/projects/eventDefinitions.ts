import type { z } from 'zod'

import type { ApiEventDefinition } from '@/schema/api'
import type { EventDefinition } from '@/schema/properties'
import { ProjectEventDefinitionsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectEventDefinitionsSchema

type Params = z.infer<typeof schema>

export const eventDefinitionsHandler: ToolBase<typeof schema, EventDefinition[]>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const eventDefsResult = await context.api.projects().eventDefinitions({
        projectId,
        search: params.q,
        limit: params.limit,
        offset: params.offset,
    })

    if (!eventDefsResult.success) {
        throw new Error(`Failed to get event definitions: ${eventDefsResult.error.message}`)
    }

    const simplifiedEvents: EventDefinition[] = eventDefsResult.data.map((def: ApiEventDefinition) => ({
        name: def.name,
        last_seen_at: def.last_seen_at,
    }))

    return simplifiedEvents
}

const tool = (): ToolBase<typeof schema, EventDefinition[]> => ({
    name: 'event-definitions-list',
    schema,
    handler: eventDefinitionsHandler,
})

export default tool
