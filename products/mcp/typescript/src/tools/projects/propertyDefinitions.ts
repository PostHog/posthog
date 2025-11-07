import { PropertyDefinitionSchema } from '@/schema/properties'
import { ProjectPropertyDefinitionsInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ProjectPropertyDefinitionsInputSchema

type Params = z.infer<typeof schema>

export const propertyDefinitionsHandler = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    if (!params.eventName && params.type === 'event') {
        throw new Error('eventName is required for event type')
    }

    const propDefsResult = await context.api.projects().propertyDefinitions({
        projectId,
        eventNames: params.eventName ? [params.eventName] : undefined,
        filterByEventNames: params.type === 'event',
        isFeatureFlag: false,
        limit: 200,
        type: params.type,
        excludeCoreProperties: !params.includePredefinedProperties,
    })

    if (!propDefsResult.success) {
        throw new Error(
            `Failed to get property definitions for ${params.type}s: ${propDefsResult.error.message}`
        )
    }

    const simplifiedProperties = PropertyDefinitionSchema.array().parse(propDefsResult.data)

    return {
        content: [{ type: 'text', text: JSON.stringify(simplifiedProperties) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'properties-list',
    schema,
    handler: propertyDefinitionsHandler,
})

export default tool
