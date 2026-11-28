import { z } from 'zod'

import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { mergeToolFactories } from '@/tools/mergeToolFactories'
import { getToolDefinitions } from '@/tools/toolDefinitions'

export function getSdkSchemas(): {
    inputs: Record<string, z.core.JSONSchema.JSONSchema>
    catalog: ReturnType<typeof getToolDefinitions>
} {
    const factories = mergeToolFactories({ generated: GENERATED_TOOL_MAP, handwritten: TOOL_MAP })
    const inputs = Object.fromEntries(
        Object.entries(factories).map(([name, factory]) => [
            name,
            z.toJSONSchema(factory().schema, { io: 'input', reused: 'ref', unrepresentable: 'any' }),
        ])
    )
    return { inputs, catalog: getToolDefinitions() }
}
