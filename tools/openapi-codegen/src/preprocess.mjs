/**
 * OpenAPI schema preprocessing to fix known Orval code generation issues.
 *
 * Two patterns are handled before handing schemas to Orval:
 *
 * 1. Named schemas with meaningless PascalCase keys (SCHEMAS_TO_INLINE)
 *    TimezoneEnum has 596 IANA identifiers like "Africa/Abidjan" that become
 *    "AfricaAbidjan" — losing the path separator and making lookups impossible.
 *    We delete the schema and replace every $ref with { type: 'string' }.
 *
 * 2. Inline ordering enums with colliding keys (stripCollidingInlineEnums)
 *    DRF ordering params include both "created_at" and "-created_at", which
 *    both PascalCase to "CreatedAt" — producing an object with duplicate keys
 *    where the second silently overwrites the first. We detect this pattern
 *    (any enum with both "x" and "-x" values) and drop the enum constraint
 *    so orval emits string[] instead.
 */

/** Schema names that should be inlined as { type: 'string' } instead of referenced. */
export const SCHEMAS_TO_INLINE = new Set(['TimezoneEnum'])

/**
 * Replace $refs to SCHEMAS_TO_INLINE entries with { type: 'string' } in-place.
 */
export function inlineSchemaRefs(obj) {
    if (!obj || typeof obj !== 'object') {
        return obj
    }
    if (obj.$ref && SCHEMAS_TO_INLINE.has(obj.$ref.replace('#/components/schemas/', ''))) {
        return { type: 'string' }
    }
    for (const [key, value] of Object.entries(obj)) {
        obj[key] = inlineSchemaRefs(value)
    }
    return obj
}

/**
 * Remove enum arrays where both "x" and "-x" appear (colliding PascalCase keys).
 * Applied in-place recursively.
 */
export function stripCollidingInlineEnums(obj) {
    if (!obj || typeof obj !== 'object') {
        return
    }
    if (Array.isArray(obj)) {
        obj.forEach(stripCollidingInlineEnums)
        return
    }
    if (obj.type === 'string' && Array.isArray(obj.enum)) {
        const positives = new Set(obj.enum.filter((v) => !v.startsWith('-')))
        if (obj.enum.some((v) => v.startsWith('-') && positives.has(v.slice(1)))) {
            delete obj.enum
        }
    }
    for (const value of Object.values(obj)) {
        stripCollidingInlineEnums(value)
    }
}

/**
 * Run standard preprocessing on a full OpenAPI schema.
 * Mutates the schema in place, also returns it for convenience.
 */
export function preprocessSchema(schema) {
    inlineSchemaRefs(schema)
    for (const name of SCHEMAS_TO_INLINE) {
        delete schema.components?.schemas?.[name]
    }
    stripCollidingInlineEnums(schema)
    return schema
}
