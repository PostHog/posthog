/**
 * Converts JSON Schema definitions from schema.json into Zod source code.
 *
 * This is a build-time code generator — it produces static TypeScript strings,
 * not runtime Zod objects. The output is written into generated tool files.
 *
 * Supports the subset of JSON Schema used by PostHog's query schemas:
 * - $ref, type, const, enum, properties, required, items
 * - anyOf/oneOf (→ z.union), allOf (→ z.intersection)
 * - type arrays like ["string", "null"] (→ z.string().nullable())
 * - additionalProperties, default, description
 */

export interface JsonSchema {
    $ref?: string
    type?: string | string[]
    const?: unknown
    enum?: unknown[]
    properties?: Record<string, JsonSchema>
    required?: string[]
    items?: JsonSchema
    anyOf?: JsonSchema[]
    oneOf?: JsonSchema[]
    allOf?: JsonSchema[]
    additionalProperties?: boolean | JsonSchema
    default?: unknown
    description?: string
    maxLength?: number
    minimum?: number
    maximum?: number
    format?: string
    nullable?: boolean
    readOnly?: boolean
}

export interface JsonSchemaRoot {
    definitions: Record<string, JsonSchema>
}

interface ConvertContext {
    root: JsonSchemaRoot
    /** Definitions that have been emitted as named variables */
    emittedDefs: Set<string>
    /** Definitions we need to emit (discovered via $ref) */
    pendingDefs: Set<string>
    /** Properties to exclude from the top-level schema */
    excludeProperties: Set<string>
    /** Whether we're at the top-level schema (for exclude_properties) */
    isTopLevel: boolean
}

/**
 * Generate Zod source code for a schema.json definition and all its transitive dependencies.
 *
 * Returns a string of TypeScript code that declares Zod schemas as `const` variables.
 * The entry point schema is the last variable declared, named after `entryDefName`.
 */
export function generateZodFromSchemaRef(
    root: JsonSchemaRoot,
    entryDefName: string,
    excludeProperties: string[] = []
): string {
    const ctx: ConvertContext = {
        root,
        emittedDefs: new Set(),
        pendingDefs: new Set(),
        excludeProperties: new Set(excludeProperties),
        isTopLevel: false,
    }

    // Collect all transitive refs first so we can emit them in dependency order
    const ordered = topologicalSort(root, entryDefName, excludeProperties)

    const lines: string[] = []
    for (const defName of ordered) {
        if (ctx.emittedDefs.has(defName)) {
            continue
        }
        ctx.emittedDefs.add(defName)
        const schema = root.definitions[defName]
        if (!schema) {
            continue
        }
        const isTop = defName === entryDefName
        ctx.isTopLevel = isTop
        const varName = sanitizeVarName(defName)
        const zodExpr = schemaToZod(schema, ctx)
        lines.push(`const ${varName} = ${zodExpr}`)
        ctx.isTopLevel = false
    }

    return lines.join('\n\n')
}

/**
 * Get the variable name for the entry definition.
 */
export function getEntryVarName(entryDefName: string): string {
    return sanitizeVarName(entryDefName)
}

// ------------------------------------------------------------------
// Core conversion
// ------------------------------------------------------------------

function schemaToZod(schema: JsonSchema, ctx: ConvertContext): string {
    // $ref
    if (schema.$ref) {
        const refName = schema.$ref.replace('#/definitions/', '')
        return sanitizeVarName(refName)
    }

    // const
    if (schema.const !== undefined) {
        return `z.literal(${JSON.stringify(schema.const)})`
    }

    // enum
    if (schema.enum) {
        if (schema.enum.length === 1) {
            return `z.literal(${JSON.stringify(schema.enum[0])})`
        }
        const members = schema.enum.map((v) => JSON.stringify(v)).join(', ')
        // Check if all enum values are strings
        if (schema.enum.every((v) => typeof v === 'string')) {
            return `z.enum([${members}])`
        }
        // Mixed types — use union of literals
        const literals = schema.enum.map((v) => `z.literal(${JSON.stringify(v)})`).join(', ')
        return `z.union([${literals}])`
    }

    // anyOf / oneOf → z.union
    if (schema.anyOf || schema.oneOf) {
        const variants = (schema.anyOf || schema.oneOf)!
        if (variants.length === 1) {
            return schemaToZod(variants[0]!, ctx)
        }
        const members = variants.map((v) => schemaToZod(v, ctx)).join(', ')
        return `z.union([${members}])`
    }

    // allOf → merge/intersection
    if (schema.allOf) {
        if (schema.allOf.length === 1) {
            return schemaToZod(schema.allOf[0]!, ctx)
        }
        const members = schema.allOf.map((v) => schemaToZod(v, ctx))
        // Use .merge for object schemas, intersection for others
        return members.reduce((acc, m) => `${acc}.and(${m})`)
    }

    // type array (e.g. ["string", "null"])
    if (Array.isArray(schema.type)) {
        const types = schema.type.filter((t) => t !== 'null')
        const hasNull = schema.type.includes('null')
        const base =
            types.length === 1
                ? primitiveToZod(types[0]!)
                : `z.union([${types.map((t) => primitiveToZod(t)).join(', ')}])`
        return hasNull ? `${base}.nullable()` : base
    }

    // object
    if (schema.type === 'object' || schema.properties) {
        return objectToZod(schema, ctx)
    }

    // array
    if (schema.type === 'array') {
        const itemSchema = schema.items ? schemaToZod(schema.items, ctx) : 'z.unknown()'
        return `z.array(${itemSchema})`
    }

    // integer special ref — use coerce for MCP client compatibility (some clients send numbers as strings)
    if (schema.type === 'integer') {
        return 'z.coerce.number().int()'
    }

    // primitives
    if (schema.type) {
        return primitiveToZod(schema.type as string)
    }

    // Fallback
    return 'z.unknown()'
}

/** Use z.coerce for numbers/booleans — some MCP clients send primitives as strings */
function primitiveToZod(type: string): string {
    switch (type) {
        case 'string':
            return 'z.string()'
        case 'number':
            return 'z.coerce.number()'
        case 'integer':
            return 'z.coerce.number().int()'
        case 'boolean':
            return 'z.coerce.boolean()'
        case 'null':
            return 'z.null()'
        default:
            return 'z.unknown()'
    }
}

function objectToZod(schema: JsonSchema, ctx: ConvertContext): string {
    const props = schema.properties ?? {}
    const required = new Set(schema.required ?? [])

    const fields: string[] = []
    for (const [name, propSchema] of Object.entries(props)) {
        // Skip excluded properties at the top level
        if (ctx.isTopLevel && ctx.excludeProperties.has(name)) {
            continue
        }
        // Skip response/readOnly fields — not relevant for tool input
        if (name === 'response' || propSchema.readOnly) {
            continue
        }

        let zodType = schemaToZod(propSchema, ctx)

        // Add .describe() if there's a description
        if (propSchema.description) {
            const escaped = propSchema.description.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n')
            zodType = `${zodType}.describe('${escaped}')`
        }

        // Add .default() if there's a default value or a const (const properties auto-fill)
        if (propSchema.default !== undefined) {
            zodType = `${zodType}.default(${JSON.stringify(propSchema.default)})`
        } else if (propSchema.const !== undefined) {
            zodType = `${zodType}.default(${JSON.stringify(propSchema.const)})`
        }

        // Make optional if not required
        if (!required.has(name)) {
            zodType = `${zodType}.optional()`
        }

        fields.push(`    ${sanitizePropName(name)}: ${zodType},`)
    }

    const obj = `z.object({\n${fields.join('\n')}\n})`
    return obj
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

/** Topological sort of schema definitions by dependency order */
function topologicalSort(root: JsonSchemaRoot, entryDefName: string, excludeProperties: string[] = []): string[] {
    const visited = new Set<string>()
    const result: string[] = []
    const excludeSet = new Set(excludeProperties)

    function visit(defName: string, isEntry: boolean = false): void {
        if (visited.has(defName)) {
            return
        }
        visited.add(defName)
        const schema = root.definitions[defName]
        if (!schema) {
            return
        }
        // For the entry definition, filter out excluded properties before collecting refs
        const effectiveSchema = isEntry && excludeSet.size > 0 ? filterProperties(schema, excludeSet) : schema
        for (const ref of collectDirectRefs(effectiveSchema)) {
            visit(ref)
        }
        result.push(defName)
    }

    visit(entryDefName, true)
    return result
}

/** Return a copy of the schema with certain properties removed */
function filterProperties(schema: JsonSchema, excludeSet: Set<string>): JsonSchema {
    if (!schema.properties) {
        return schema
    }
    const filtered: Record<string, JsonSchema> = {}
    for (const [name, prop] of Object.entries(schema.properties)) {
        if (!excludeSet.has(name) && name !== 'response' && !prop.readOnly) {
            filtered[name] = prop
        }
    }
    return { ...schema, properties: filtered }
}

/** Collect $ref names directly referenced by a schema (non-recursive) */
function collectDirectRefs(schema: JsonSchema): string[] {
    const refs: string[] = []

    function walk(s: JsonSchema | undefined): void {
        if (!s) {
            return
        }
        if (s.$ref) {
            refs.push(s.$ref.replace('#/definitions/', ''))
            return
        }
        if (s.properties) {
            for (const prop of Object.values(s.properties)) {
                walk(prop)
            }
        }
        if (s.items) {
            walk(s.items)
        }
        if (s.anyOf) {
            for (const v of s.anyOf) {
                walk(v)
            }
        }
        if (s.oneOf) {
            for (const v of s.oneOf) {
                walk(v)
            }
        }
        if (s.allOf) {
            for (const v of s.allOf) {
                walk(v)
            }
        }
        if (typeof s.additionalProperties === 'object') {
            walk(s.additionalProperties)
        }
    }

    walk(schema)
    return refs
}

/** Sanitize a definition name to a valid JS variable name */
function sanitizeVarName(name: string): string {
    // Handle names like "AnyEntityNode<DataWarehouseNode>"
    return name.replace(/[<>]/g, '_').replace(/[^a-zA-Z0-9_$]/g, '_')
}

/** Sanitize a property name — quote if it contains special chars */
function sanitizePropName(name: string): string {
    if (/^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(name)) {
        return name
    }
    return `'${name}'`
}
