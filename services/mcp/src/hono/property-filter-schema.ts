import type { Tool as McpTool } from '@modelcontextprotocol/sdk/types.js'

type Schema = boolean | SchemaObject

type SchemaObject = {
    type?: string
    properties?: Record<string, Schema>
    required?: string[]
    items?: Schema
    anyOf?: Schema[]
    oneOf?: Schema[]
    allOf?: Schema[]
}

function isOpenObject(variant: Schema): variant is SchemaObject & { properties: Record<string, Schema> } {
    return (
        typeof variant === 'object' &&
        variant.type === 'object' &&
        variant.properties !== undefined &&
        Object.keys(variant).every((key) => ['type', 'properties', 'required'].includes(key))
    )
}

function factorFilterVariants(schema: SchemaObject): SchemaObject {
    const variants = schema.anyOf
    // Moving fields out of a closed object would make the branch reject them.
    if (!variants || variants.length < 2 || Object.keys(schema).length !== 1 || !variants.every(isOpenObject)) {
        return schema
    }

    const first = variants[0]!
    if (!first.properties.operator) {
        return schema
    }

    const properties = Object.fromEntries(
        Object.entries(first.properties).filter(([name, property]) => {
            const serialized = JSON.stringify(property)
            const required = first.required?.includes(name) ?? false
            return variants.every(
                (variant) =>
                    (variant.required?.includes(name) ?? false) === required &&
                    JSON.stringify(variant.properties[name]) === serialized
            )
        })
    )

    if (!properties.type || !properties.key) {
        return schema
    }

    const sharedFields = new Set(Object.keys(properties))
    const required = first.required?.filter((name) => sharedFields.has(name))
    return {
        type: 'object',
        properties,
        ...(required?.length ? { required } : {}),
        anyOf: variants.map((variant) => {
            const fields = Object.entries(variant.properties).filter(([name]) => !sharedFields.has(name))
            const required = variant.required?.filter((name) => !sharedFields.has(name))
            return {
                type: 'object',
                properties: Object.fromEntries(fields),
                ...(required?.length ? { required } : {}),
            }
        }),
    }
}

function compact(schema: Schema): Schema {
    if (typeof schema === 'boolean') {
        return schema
    }
    const result = { ...schema }
    if (schema.properties) {
        result.properties = Object.fromEntries(
            Object.entries(schema.properties).map(([name, value]) => [name, compact(value)])
        )
    }
    if (schema.items !== undefined && !Array.isArray(schema.items)) {
        result.items = compact(schema.items)
    }
    for (const keyword of ['anyOf', 'oneOf', 'allOf'] as const) {
        if (schema[keyword]) {
            result[keyword] = schema[keyword].map(compact)
        }
    }
    return factorFilterVariants(result)
}

export function compactPropertyFilterSchema(schema: McpTool['inputSchema']): McpTool['inputSchema'] {
    const serialized = JSON.stringify(schema)
    // Moving an addressed property would invalidate its JSON Pointer.
    if (!serialized.includes('"operator":') || /"\$(ref|dynamicRef|recursiveRef)":/.test(serialized)) {
        return schema
    }
    return compact(schema as SchemaObject) as McpTool['inputSchema']
}
