import type { z } from 'zod'

import type { ApiPropertyDefinition } from '@/schema/api'
import { PropertyDefinitionUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = PropertyDefinitionUpdateSchema

type Params = z.infer<typeof schema>

type Result = ApiPropertyDefinition & { url: string }

export const updatePropertyDefinitionHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.projects().updatePropertyDefinition({
        projectId,
        propertyName: params.propertyName,
        type: params.type,
        groupTypeIndex: params.groupTypeIndex,
        data: params.data,
    })

    if (!result.success) {
        throw new Error(`Failed to update property definition: ${result.error.message}`)
    }

    return {
        ...result.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/data-management/properties/${encodeURIComponent(result.data.id)}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'property-definition-update',
    schema,
    handler: updatePropertyDefinitionHandler,
})

export default tool
