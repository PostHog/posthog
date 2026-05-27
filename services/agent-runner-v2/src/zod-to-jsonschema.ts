/**
 * Minimal zod → JSON Schema converter for tool input declarations sent to
 * pi.dev. Handles the shapes used by native tools (object/string/number/
 * boolean/array/record/optional/default/literal/union).
 *
 * Not a general solution — there are full-featured packages (zod-to-json-schema)
 * but we want zero deps and need only the shapes the native tools use.
 */

import type { ZodTypeAny } from 'zod'

interface JsonSchema {
    type?: string | string[]
    description?: string
    properties?: Record<string, JsonSchema>
    required?: string[]
    items?: JsonSchema | JsonSchema[]
    enum?: unknown[]
    const?: unknown
    additionalProperties?: boolean | JsonSchema
    oneOf?: JsonSchema[]
    anyOf?: JsonSchema[]
    [k: string]: unknown
}

export function zodToJsonSchema(schema: ZodTypeAny): JsonSchema {
    const def = schema as unknown as { _zod?: { def?: unknown }; _def?: unknown }
    const inner = (def._zod?.def ?? def._def) as { type?: string; [k: string]: unknown } | undefined
    if (!inner) {
        return { type: 'object' }
    }

    const description = (schema as unknown as { description?: string }).description

    const out: JsonSchema = {}
    if (description) {
        out.description = description
    }

    switch (inner.type) {
        case 'string':
            return { type: 'string', ...out }
        case 'number':
        case 'int':
            return { type: 'number', ...out }
        case 'boolean':
            return { type: 'boolean', ...out }
        case 'literal':
            return { const: (inner as { values?: unknown[] }).values?.[0], ...out }
        case 'enum': {
            const values = (inner as { entries?: Record<string, unknown> }).entries
            return { enum: values ? Object.values(values) : [], ...out }
        }
        case 'array':
            return {
                type: 'array',
                items: zodToJsonSchema((inner as { element: ZodTypeAny }).element),
                ...out,
            }
        case 'object': {
            const shape = (inner as { shape: Record<string, ZodTypeAny> }).shape
            const properties: Record<string, JsonSchema> = {}
            const required: string[] = []
            for (const [key, child] of Object.entries(shape)) {
                properties[key] = zodToJsonSchema(child)
                if (!isOptional(child)) {
                    required.push(key)
                }
            }
            return { type: 'object', properties, required, additionalProperties: false, ...out }
        }
        case 'record':
            return {
                type: 'object',
                additionalProperties: zodToJsonSchema((inner as { valueType: ZodTypeAny }).valueType),
                ...out,
            }
        case 'optional':
        case 'default':
            return zodToJsonSchema((inner as { innerType: ZodTypeAny }).innerType)
        case 'union': {
            const options = (inner as { options: ZodTypeAny[] }).options
            return { oneOf: options.map(zodToJsonSchema), ...out }
        }
        case 'any':
        case 'unknown':
            return { ...out }
        default:
            return { type: 'object', ...out }
    }
}

function isOptional(schema: ZodTypeAny): boolean {
    const inner = ((schema as unknown as { _zod?: { def?: unknown }; _def?: unknown })._zod?.def ??
        (schema as unknown as { _def?: unknown })._def) as { type?: string } | undefined
    return inner?.type === 'optional' || inner?.type === 'default'
}
