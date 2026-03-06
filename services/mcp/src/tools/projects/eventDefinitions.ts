import type { z } from 'zod'

import type { ApiEventDefinition } from '@/schema/api'
import { EventDefinitionSchema } from '@/schema/properties'
import { ProjectEventDefinitionsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectEventDefinitionsSchema

type Params = z.infer<typeof schema>

export const eventDefinitionsHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
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

    const simplifiedEvents = eventDefsResult.data.map((def: ApiEventDefinition) => EventDefinitionSchema.parse(def))

    return simplifiedEvents
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'event-definitions-list',
    schema,
    handler: eventDefinitionsHandler,
})

export default tool
