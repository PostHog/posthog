/**
 * Build-time JSON Schema → Zod source generator for OpenAPI component schemas.
 *
 * Ported from services/mcp/scripts/lib/json-schema-to-zod.ts with:
 * - #/components/schemas/ $ref paths (OpenAPI) instead of #/definitions/
 * - integer minimum/maximum on schema nodes
 * - no readOnly property skipping (widget config schemas are documentation-shaped)
 */

/** @typedef {Record<string, unknown>} JsonSchema */

/**
 * @param {string} name
 */
function sanitizeVarName(name) {
    return name.charAt(0).toLowerCase() + name.slice(1)
}

/**
 * @param {string} name
 */
function sanitizePropName(name) {
    return /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(name) ? name : JSON.stringify(name)
}

/**
 * @param {string} ref
 */
function refToSchemaName(ref) {
    return ref.replace('#/components/schemas/', '').replace('#/definitions/', '')
}

/**
 * @param {JsonSchema} schema
 * @param {Set<string>} [topLevelExcludes]
 * @returns {string[]}
 */
function collectDirectRefs(schema, topLevelExcludes = new Set()) {
    /** @type {string[]} */
    const refs = []

    /**
     * @param {JsonSchema | undefined} s
     * @param {boolean} isTop
     */
    function walk(s, isTop) {
        if (!s) {
            return
        }
        if (s.$ref) {
            refs.push(refToSchemaName(s.$ref))
            return
        }
        if (s.properties) {
            for (const [name, prop] of Object.entries(s.properties)) {
                if (isTop && topLevelExcludes.has(name)) {
                    continue
                }
                walk(prop, false)
            }
        }
        for (const key of ['items', 'additionalProperties']) {
            const child = s[key]
            if (child && typeof child === 'object') {
                walk(child, false)
            }
        }
        for (const key of ['anyOf', 'oneOf', 'allOf']) {
            const variants = s[key]
            if (Array.isArray(variants)) {
                for (const variant of variants) {
                    walk(variant, false)
                }
            }
        }
    }

    walk(schema, true)
    return refs
}

/**
 * @param {Record<string, JsonSchema>} definitions
 * @param {string} entryDefName
 * @param {Set<string>} [topLevelExcludes]
 * @returns {string[]}
 */
function topologicalSort(definitions, entryDefName, topLevelExcludes = new Set()) {
    const visited = new Set()
    /** @type {string[]} */
    const result = []

    /**
     * @param {string} defName
     * @param {boolean} [isEntry]
     */
    function visit(defName, isEntry = false) {
        if (visited.has(defName)) {
            return
        }
        visited.add(defName)
        const schema = definitions[defName]
        if (!schema) {
            return
        }
        const excludes = isEntry ? topLevelExcludes : new Set()
        for (const ref of collectDirectRefs(schema, excludes)) {
            visit(ref)
        }
        result.push(defName)
    }

    visit(entryDefName, true)
    return result
}

/**
 * @param {JsonSchema} schema
 * @param {{ excludeProperties: Set<string>, isTopLevel: boolean }} ctx
 * @returns {string}
 */
function applyNumericConstraints(schema, zodExpr) {
    if (schema.type !== 'integer' && schema.type !== 'number') {
        return zodExpr
    }
    if (typeof schema.minimum === 'number') {
        zodExpr += `.min(${schema.minimum})`
    }
    if (typeof schema.maximum === 'number') {
        zodExpr += `.max(${schema.maximum})`
    }
    return zodExpr
}

/**
 * @param {string} type
 */
function primitiveToZod(type) {
    switch (type) {
        case 'string':
            return 'zod.string()'
        case 'number':
            return 'zod.number()'
        case 'integer':
            return 'zod.number().int()'
        case 'boolean':
            return 'zod.boolean()'
        case 'null':
            return 'zod.null()'
        default:
            return 'zod.unknown()'
    }
}

/**
 * @param {JsonSchema} schema
 * @param {{ excludeProperties: Set<string>, isTopLevel: boolean }} ctx
 * @returns {string}
 */
function schemaToZod(schema, ctx) {
    if (schema.$ref) {
        return sanitizeVarName(refToSchemaName(schema.$ref))
    }

    if (schema.const !== undefined) {
        return `zod.literal(${JSON.stringify(schema.const)})`
    }

    if (schema.enum) {
        if (schema.enum.length === 1) {
            return `zod.literal(${JSON.stringify(schema.enum[0])})`
        }
        if (schema.enum.every((value) => typeof value === 'string')) {
            return `zod.enum([${schema.enum.map((value) => JSON.stringify(value)).join(', ')}])`
        }
        return `zod.union([${schema.enum.map((value) => `zod.literal(${JSON.stringify(value)})`).join(', ')}])`
    }

    const variants = schema.anyOf ?? schema.oneOf
    if (variants) {
        if (variants.length === 1) {
            return schemaToZod(variants[0], ctx)
        }
        return `zod.union([${variants.map((variant) => schemaToZod(variant, ctx)).join(', ')}])`
    }

    if (schema.allOf) {
        if (schema.allOf.length === 1) {
            let zodExpr = schemaToZod(schema.allOf[0], ctx)
            zodExpr = applyNumericConstraints(schema, zodExpr)
            return zodExpr
        }
        return schema.allOf.map((variant) => schemaToZod(variant, ctx)).reduce((acc, expr) => `${acc}.and(${expr})`)
    }

    if (Array.isArray(schema.type)) {
        const types = schema.type.filter((type) => type !== 'null')
        const hasNull = schema.type.includes('null')
        const base =
            types.length === 1
                ? primitiveToZod(types[0])
                : `zod.union([${types.map((type) => primitiveToZod(type)).join(', ')}])`
        return hasNull ? `${base}.nullable()` : base
    }

    if (schema.type === 'object' || schema.properties) {
        return objectToZod(schema, ctx)
    }

    if (schema.type === 'array') {
        const itemSchema = schema.items ? schemaToZod(schema.items, ctx) : 'zod.unknown()'
        let zodExpr = `zod.array(${itemSchema})`
        if (typeof schema.minItems === 'number') {
            zodExpr += `.min(${schema.minItems})`
        }
        if (typeof schema.maxItems === 'number') {
            zodExpr += `.max(${schema.maxItems})`
        }
        return zodExpr
    }

    if (schema.type) {
        return applyNumericConstraints(schema, primitiveToZod(schema.type))
    }

    return 'zod.unknown()'
}

/**
 * @param {JsonSchema} schema
 * @param {{ excludeProperties: Set<string>, isTopLevel: boolean }} ctx
 * @returns {string}
 */
function objectToZod(schema, ctx) {
    const props = schema.properties ?? {}
    const required = new Set(schema.required ?? [])
    const ap = schema.additionalProperties
    const apSchema = typeof ap === 'object' && ap !== null ? ap : null

    if (Object.keys(props).length === 0 && apSchema) {
        return `zod.record(zod.string(), ${schemaToZod(apSchema, ctx)})`
    }

    if (Object.keys(props).length === 0 && ap !== false) {
        return 'zod.record(zod.string(), zod.unknown())'
    }

    /** @type {string[]} */
    const fields = []
    for (const [name, propSchema] of Object.entries(props)) {
        if (ctx.isTopLevel && ctx.excludeProperties.has(name)) {
            continue
        }

        let zodType = schemaToZod(propSchema, ctx)
        zodType = applyNumericConstraints(propSchema, zodType)

        if (propSchema.description) {
            const escaped = propSchema.description
                .replace(/\\/g, '\\\\')
                .replace(/'/g, "\\'")
                .replace(/\n/g, '\\n')
            zodType = `${zodType}.describe('${escaped}')`
        }

        if (propSchema.default !== undefined) {
            zodType = `${zodType}.default(${JSON.stringify(propSchema.default)})`
        } else if (propSchema.const !== undefined) {
            zodType = `${zodType}.default(${JSON.stringify(propSchema.const)})`
        }

        if (!required.has(name)) {
            zodType = `${zodType}.optional()`
        }

        fields.push(`    ${sanitizePropName(name)}: ${zodType},`)
    }

    const obj = `zod.object({\n${fields.join('\n')}\n})`
    if (apSchema) {
        return `${obj}.catchall(${schemaToZod(apSchema, ctx)})`
    }
    return obj
}

/**
 * Generate Zod source for an OpenAPI components/schemas entry and its transitive deps.
 *
 * @param {Record<string, JsonSchema>} componentSchemas
 * @param {string} entrySchemaName
 * @param {{ excludeProperties?: string[], exportName?: string }} [options]
 * @returns {{ body: string, entryVarName: string }}
 */
export function generateZodFromOpenApiComponent(componentSchemas, entrySchemaName, options = {}) {
    const excludeProperties = new Set(options.excludeProperties ?? [])
    const ordered = topologicalSort(componentSchemas, entrySchemaName, excludeProperties)
    const emitted = new Set()
    /** @type {string[]} */
    const lines = []

    for (const schemaName of ordered) {
        if (emitted.has(schemaName)) {
            continue
        }
        emitted.add(schemaName)
        const schema = componentSchemas[schemaName]
        if (!schema) {
            continue
        }
        const ctx = {
            excludeProperties,
            isTopLevel: schemaName === entrySchemaName,
        }
        const varName = sanitizeVarName(schemaName)
        lines.push(`const ${varName} = /* @__PURE__ */ ${schemaToZod(schema, ctx)}`)
    }

    const entryVarName = sanitizeVarName(entrySchemaName)
    return { body: lines.join('\n\n'), entryVarName }
}

/**
 * @param {object} catalogSlice - output of filterSchemaByOperationIds
 * @param {string[]} entrySchemaNames
 * @param {(schemaName: string) => string} exportNameForSchema
 * @returns {string}
 */
export function generateWidgetConfigZodModule(catalogSlice, entrySchemaNames, exportNameForSchema) {
    const componentSchemas = catalogSlice.components?.schemas ?? {}
    const ordered = [
        ...new Set(
            entrySchemaNames.flatMap((schemaName) => topologicalSort(componentSchemas, schemaName, new Set()))
        ),
    ]

    /** @type {string[]} */
    const helperLines = []
    for (const schemaName of ordered) {
        const schema = componentSchemas[schemaName]
        if (!schema) {
            continue
        }
        const varName = sanitizeVarName(schemaName)
        helperLines.push(
            `const ${varName} = /* @__PURE__ */ ${schemaToZod(schema, { excludeProperties: new Set(), isTopLevel: false })}`
        )
    }

    const exportLines = entrySchemaNames
        .sort()
        .map(
            (schemaName) =>
                `export const ${exportNameForSchema(schemaName)} = /* @__PURE__ */ ${sanitizeVarName(schemaName)}`
        )

    return [
        `/** Auto-generated from products/dashboards/backend/widget_specs — do not edit.
 * Regenerate: hogli build:widget-types
 */
import { z as zod } from 'zod'`,
        ...helperLines,
        ...exportLines,
    ].join('\n\n') + '\n'
}
