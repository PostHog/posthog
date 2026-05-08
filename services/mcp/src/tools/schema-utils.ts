/** Token-aware schema summarization and drill-down utilities for the exec tool. */

// 12k tokens × 4 chars/token
export const TOKEN_CHAR_LIMIT = 4 * 12_000

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
 * JSON Schema composition keywords that fan out into more sub-schemas.
 * A named child may live under any of these; resolution walks them transparently.
 */
const COMPOSITION_KEYS = ['allOf', 'anyOf', 'oneOf'] as const

function getVariants(node: JSONSchema, key: (typeof COMPOSITION_KEYS)[number]): JSONSchema[] | undefined {
    const value = node[key]
    return Array.isArray(value) ? (value as JSONSchema[]) : undefined
}

/**
 * Find a named child of a schema node, regardless of how the schema composes it.
 *
 * Walks `properties`, every composition keyword (`allOf`/`anyOf`/`oneOf`), and `items`
 * recursively — so `series.event` works whether `event` lives on `items.properties`,
 * `items.anyOf[i].properties`, `items.allOf[i].properties`, or any nested combination.
 *
 * First match wins. `seen` blocks pathological cycles if schemas ever carry self-refs
 * (Zod's `toJSONSchema` inlines, so this is defensive).
 */
function findNamedChild(node: JSONSchema, name: string, seen: WeakSet<JSONSchema> = new WeakSet()): JSONSchema | null {
    if (seen.has(node)) {
        return null
    }
    seen.add(node)

    if (node.properties) {
        const direct = (node.properties as Record<string, JSONSchema>)[name]
        if (direct) {
            return direct
        }
    }

    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(node, key)
        if (!variants) {
            continue
        }
        for (const variant of variants) {
            const hit = findNamedChild(variant, name, seen)
            if (hit) {
                return hit
            }
        }
    }

    // Array children are whatever `items` exposes — recurse transparently.
    // Tuple form (`items: [...]`) is ignored; Zod doesn't produce it and it would need
    // index-specific handling anyway.
    if (node.items && !Array.isArray(node.items)) {
        const hit = findNamedChild(node.items as JSONSchema, name, seen)
        if (hit) {
            return hit
        }
    }

    return null
}

/**
 * Resolve a numeric index: descend into array items or pick a union variant by position.
 * Arrays take precedence (all items share the same schema, so index 0/N returns the
 * same items wrapper); for unions, `0` picks the first variant, `1` the second, etc.
 */
function findIndexedChild(node: JSONSchema, idx: number): JSONSchema | null {
    if (node.items && !Array.isArray(node.items)) {
        return node.items as JSONSchema
    }
    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(node, key)
        if (variants && variants[idx]) {
            return variants[idx] as JSONSchema
        }
    }
    return null
}

/**
 * Collect every named child reachable from a node by walking composition keywords.
 * Dedupes across variants.
 */
function collectNamedChildren(
    node: JSONSchema,
    into: Set<string> = new Set(),
    seen: WeakSet<JSONSchema> = new WeakSet()
): Set<string> {
    if (seen.has(node)) {
        return into
    }
    seen.add(node)

    if (node.properties) {
        for (const k of Object.keys(node.properties as Record<string, unknown>)) {
            into.add(k)
        }
    }
    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(node, key)
        if (!variants) {
            continue
        }
        for (const variant of variants) {
            collectNamedChildren(variant, into, seen)
        }
    }
    return into
}

/**
 * Resolve a dot-separated path within a JSON Schema.
 * Returns the sub-schema at that path, or null if invalid.
 */
export function resolveSchemaPath(schema: JSONSchema, dotPath: string): JSONSchema | null {
    let current: JSONSchema = schema
    for (const segment of dotPath.split('.')) {
        const isNumeric = /^\d+$/.test(segment)
        const next = isNumeric
            ? (findIndexedChild(current, parseInt(segment, 10)) ?? findNamedChild(current, segment))
            : findNamedChild(current, segment)
        if (!next) {
            return null
        }
        current = next
    }
    return current
}

/**
 * List available child paths from a schema node.
 * Emits:
 *   - every named child reachable through any composition keyword (direct or nested)
 *   - `[items].<name>` for array-of-object/array-of-union items (via composition walk)
 *   - numeric variant labels when the node itself is a union
 */
export function listAvailablePaths(schema: JSONSchema): string[] {
    const paths: string[] = []

    // Named children at this level (covers properties + allOf/anyOf/oneOf at any nesting).
    for (const k of collectNamedChildren(schema)) {
        paths.push(k)
    }

    // Array item children, surfaced under `[items].<name>` so callers know they're
    // indexing through an array.
    if (schema.type === 'array' && schema.items && !Array.isArray(schema.items)) {
        const itemChildren = collectNamedChildren(schema.items as JSONSchema)
        for (const k of itemChildren) {
            paths.push(`[items].${k}`)
        }
    }

    // If the node is itself a union, expose variant indices so callers can pick by position.
    for (const key of COMPOSITION_KEYS) {
        const variants = getVariants(schema, key)
        if (!variants || key === 'allOf') {
            continue
        }
        for (let i = 0; i < variants.length; i++) {
            const v = variants[i]!
            const label = typeof v.title === 'string' ? `${i} (${v.title})` : `${i}`
            paths.push(label)
        }
    }

    return paths
}
