import { EventDefinitionSchema } from '@/schema/properties'
import { ProjectEventDefinitionsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ProjectEventDefinitionsSchema

type Params = z.infer<typeof schema>

export const eventDefinitionsHandler = async (context: Context, _params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const eventDefsResult = await context.api
        .projects()
        .eventDefinitions({ projectId, search: _params.q })

    if (!eventDefsResult.success) {
        throw new Error(`Failed to get event definitions: ${eventDefsResult.error.message}`)
    }

    const simplifiedEvents = eventDefsResult.data.map((def) => EventDefinitionSchema.parse(def))

    return {
        content: [{ type: 'text', text: JSON.stringify(simplifiedEvents) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'event-definitions-list',
    schema,
    handler: eventDefinitionsHandler,
})

export default tool
