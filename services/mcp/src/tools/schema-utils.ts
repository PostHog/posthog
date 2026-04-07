/** Token-aware schema summarization and drill-down utilities for the exec tool. */

// 16k tokens × 6 chars/token
export const TOKEN_CHAR_LIMIT = 96_000

type JSONSchema = Record<string, unknown>

interface SummarizedProperty {
    type?: string
    description?: string
    enum?: unknown[]
    default?: unknown
    const?: unknown
    required?: boolean
    fields?: string[]
    items?: string
    hint?: string
}

interface SchemaSummary {
    type: string
    required?: string[]
    properties: Record<string, SummarizedProperty>
    note?: string
}

/**
 * Describe the type of a union (anyOf/oneOf) concisely.
 * Extracts variant names from `title`, `description`, or `const` fields.
 */
function describeUnion(variants: JSONSchema[]): string {
    const names: string[] = []
    for (const v of variants) {
        if (typeof v.title === 'string') {
            names.push(v.title)
        } else if (typeof v.const === 'string') {
            names.push(v.const)
        }
    }
    if (names.length > 0 && names.length <= 6) {
        return `union of ${variants.length} types (${names.join(', ')})`
    }
    return `union of ${variants.length} types`
}

/** Get the effective type string for a schema node. */
function getTypeString(schema: JSONSchema): string {
    if (typeof schema.type === 'string') {
        return schema.type
    }
    if (Array.isArray(schema.type)) {
        return (schema.type as string[]).filter((t) => t !== 'null').join(' | ')
    }
    if (schema.anyOf || schema.oneOf) {
        const variants = (schema.anyOf || schema.oneOf) as JSONSchema[]
        // Filter out null types for optional unions
        const nonNull = variants.filter((v) => v.type !== 'null')
        if (nonNull.length === 0) {
            return 'null'
        }
        return describeUnion(nonNull)
    }
    if (schema.const !== undefined) {
        return 'const'
    }
    return 'unknown'
}

/** Check if a property has complex nested structure that needs drill-down. */
function isComplex(schema: JSONSchema): boolean {
    if (schema.type === 'object' && schema.properties) {
        return true
    }
    if (schema.type === 'array' && schema.items) {
        const items = schema.items as JSONSchema
        if (items.type === 'object' && items.properties) {
            return true
        }
        if (items.anyOf || items.oneOf) {
            return true
        }
    }
    if (schema.anyOf || schema.oneOf) {
        const variants = (schema.anyOf || schema.oneOf) as JSONSchema[]
        const nonNull = variants.filter((v) => v.type !== 'null')
        // Simple nullable scalar is not complex
        if (nonNull.length <= 1 && nonNull.every((v) => typeof v.type === 'string' && v.type !== 'object')) {
            return false
        }
        return nonNull.length > 1 || nonNull.some((v) => v.type === 'object' || v.type === 'array')
    }
    return false
}

/** Describe array items concisely. */
function describeItems(items: JSONSchema): string {
    if (items.anyOf || items.oneOf) {
        const variants = (items.anyOf || items.oneOf) as JSONSchema[]
        return describeUnion(variants.filter((v) => v.type !== 'null'))
    }
    if (items.type === 'object') {
        const propNames = items.properties ? Object.keys(items.properties as Record<string, unknown>) : []
        if (propNames.length > 0) {
            return `object with ${propNames.length} fields`
        }
        return 'object'
    }
    return getTypeString(items)
}

/**
 * Summarize a JSON Schema's top-level properties.
 * Produces field names, types, descriptions, and drill-down hints for complex fields.
 */
export function summarizeSchema(schema: JSONSchema, toolName: string, fieldPath?: string): SchemaSummary {
    const properties = (schema.properties || {}) as Record<string, JSONSchema>
    const requiredFields = (schema.required || []) as string[]
    const result: Record<string, SummarizedProperty> = {}
    const pathPrefix = fieldPath ? `${fieldPath}.` : ''

    for (const [name, prop] of Object.entries(properties)) {
        const entry: SummarizedProperty = {}
        const typeStr = getTypeString(prop)
        entry.type = typeStr

        if (typeof prop.description === 'string') {
            entry.description = prop.description
        }
        if (prop.enum) {
            entry.enum = prop.enum as unknown[]
        }
        if (prop.default !== undefined) {
            entry.default = prop.default
        }
        if (prop.const !== undefined) {
            entry.const = prop.const
        }
        if (requiredFields.includes(name)) {
            entry.required = true
        }

        // For objects, list subfield names
        if (prop.type === 'object' && prop.properties) {
            entry.fields = Object.keys(prop.properties as Record<string, unknown>)
        }

        // For arrays, describe items
        if (prop.type === 'array' && prop.items) {
            entry.items = describeItems(prop.items as JSONSchema)
        }

        // Add drill-down hint for complex fields
        if (isComplex(prop)) {
            entry.hint = `Run \`schema ${toolName} ${pathPrefix}${name}\` for full structure`
        }

        result[name] = entry
    }

    return {
        type: (schema.type as string) || 'object',
        ...(requiredFields.length > 0 ? { required: requiredFields } : {}),
        properties: result,
    }
}

/**
 * Resolve a dot-separated path within a JSON Schema.
 * Returns the sub-schema at that path, or null if invalid.
 */
export function resolveSchemaPath(schema: JSONSchema, dotPath: string): JSONSchema | null {
    const segments = dotPath.split('.')
    let current: JSONSchema = schema

    for (const segment of segments) {
        // Try properties first
        if (current.properties) {
            const props = current.properties as Record<string, JSONSchema>
            const prop = props[segment]
            if (prop) {
                current = prop
                continue
            }
        }

        // Try array items
        if (current.type === 'array' && current.items) {
            const items = current.items as JSONSchema
            // If segment matches a property inside items
            if (items.properties) {
                const itemProps = items.properties as Record<string, JSONSchema>
                const itemProp = itemProps[segment]
                if (itemProp) {
                    current = itemProp
                    continue
                }
            }
            // If segment is numeric, descend into items
            if (/^\d+$/.test(segment)) {
                current = items
                continue
            }
        }

        // Try union variants (anyOf/oneOf)
        const variants = (current.anyOf || current.oneOf) as JSONSchema[] | undefined
        if (variants) {
            if (/^\d+$/.test(segment)) {
                const idx = parseInt(segment, 10)
                const variant = variants[idx]
                if (variant) {
                    current = variant
                    continue
                }
            }
            // Try to find property across all object variants
            let found = false
            for (const variant of variants) {
                if (variant.properties) {
                    const variantProps = variant.properties as Record<string, JSONSchema>
                    const variantProp = variantProps[segment]
                    if (variantProp) {
                        current = variantProp
                        found = true
                        break
                    }
                }
            }
            if (found) {
                continue
            }
        }

        return null
    }

    return current
}

/**
 * List available child paths from a schema node.
 */
export function listAvailablePaths(schema: JSONSchema): string[] {
    const paths: string[] = []

    if (schema.properties) {
        paths.push(...Object.keys(schema.properties as Record<string, unknown>))
    }

    if (schema.type === 'array' && schema.items) {
        const items = schema.items as JSONSchema
        if (items.properties) {
            paths.push(...Object.keys(items.properties as Record<string, unknown>).map((k) => `[items].${k}`))
        }
    }

    const variants = (schema.anyOf || schema.oneOf) as JSONSchema[] | undefined
    if (variants) {
        for (let i = 0; i < variants.length; i++) {
            const v = variants[i]!
            const label = typeof v.title === 'string' ? `${i} (${v.title})` : `${i}`
            paths.push(label)
        }
    }

    return paths
}
