import type { z } from 'zod'

import type { PropertyDefinition } from '@/schema/properties'
import { ProjectPropertyDefinitionsInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectPropertyDefinitionsInputSchema

type Params = z.infer<typeof schema>

export const propertyDefinitionsHandler: ToolBase<typeof schema, PropertyDefinition[]>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    if (!params.eventName && params.type === 'event') {
        throw new Error('eventName is required for event type')
    }

    const propDefsResult = await context.api.projects().propertyDefinitions({
        projectId,
        eventNames: params.eventName ? [params.eventName] : undefined,
        filterByEventNames: params.type === 'event',
        isFeatureFlag: false,
        limit: params.limit,
        offset: params.offset,
        type: params.type,
        excludeCoreProperties: !params.includePredefinedProperties,
    })

    if (!propDefsResult.success) {
        throw new Error(`Failed to get property definitions for ${params.type}s: ${propDefsResult.error.message}`)
    }

    const simplifiedProperties: PropertyDefinition[] = propDefsResult.data.map(
        (def: { name: string; property_type?: string | null }) => ({
            name: def.name,
            property_type: def.property_type,
        })
    )

    return simplifiedProperties
}

const tool = (): ToolBase<typeof schema, PropertyDefinition[]> => ({
    name: 'properties-list',
    schema,
    handler: propertyDefinitionsHandler,
})

export default tool
