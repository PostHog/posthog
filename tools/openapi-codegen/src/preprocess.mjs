/**
 * OpenAPI schema preprocessing to fix known Orval code generation issues.
 *
 * Three patterns are handled before handing schemas to Orval:
 *
 * 1. Named schemas that should be inlined (SCHEMAS_TO_INLINE)
 *    Each entry maps a component name to the inline schema that replaces every
 *    $ref to it. Two cases use this today:
 *      - TimezoneEnum has 596 IANA identifiers like "Africa/Abidjan" that
 *        PascalCase to "AfricaAbidjan", losing the path separator. We replace
 *        refs with { type: 'string' }.
 *      - NullEnum is drf-spectacular's named ref for a `{type: 'null'}` schema
 *        emitted alongside every nullable enum. The component is structural
 *        noise — it produces a `NullEnumApi = null` type alias that just
 *        forwards to `null`. We replace refs with { type: 'null'} so consumers
 *        see `Role | "" | null` directly.
 *
 * 2. Inline ordering enums with colliding keys (stripCollidingInlineEnums)
 *    DRF ordering params include both "created_at" and "-created_at", which
 *    both PascalCase to "CreatedAt" — producing an object with duplicate keys
 *    where the second silently overwrites the first. We detect this pattern
 *    (any enum with both "x" and "-x" values) and drop the enum constraint
 *    so orval emits string[] instead.
 *
 * 3. Integer bounds exceeding JS safe-integer range (clampIntegerBounds)
 *    drf-spectacular emits i64 bounds (±9223372036854775807) for BigAutoField
 *    primary keys. JSON.parse silently rounds 2^63-1 up to 2^63 (losing
 *    precision), and downstream consumers — including Anthropic's tool-schema
 *    validator, which parses bounds as i64 — then reject the overflowed value.
 *    We clamp any integer schema's min/max/exclusiveMin/exclusiveMax to int32
 *    range, which is far more than enough for every PostHog identifier.
 */

export const INT32_MIN = -2147483648
export const INT32_MAX = 2147483647
const INTEGER_BOUND_KEYS = ['minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum']

/**
 * Component names whose $refs get replaced inline, mapped to the substitute schema.
 * The component itself is also removed from `components.schemas` after substitution.
 */
export const SCHEMAS_TO_INLINE = new Map([
    ['TimezoneEnum', { type: 'string' }],
    ['NullEnum', { type: 'null' }],
])

/**
 * Replace $refs to SCHEMAS_TO_INLINE entries with their substitute schema in-place.
 */
export function inlineSchemaRefs(obj) {
    if (!obj || typeof obj !== 'object') {
        return obj
    }
    if (obj.$ref) {
        const name = obj.$ref.replace('#/components/schemas/', '')
        const substitute = SCHEMAS_TO_INLINE.get(name)
        if (substitute) {
            return { ...substitute }
        }
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
 * Clamp integer bounds that exceed int32 range.
 *
 * Applied in-place to any object shaped like `{ type: 'integer', ... }`, where
 * "integer" is either the literal type or present in a `type` array. Bounds
 * outside ±2^31-1 are rewritten to the nearest int32 limit; values already
 * within range are left untouched.
 */
export function clampIntegerBounds(obj) {
    if (!obj || typeof obj !== 'object') {
        return
    }
    if (Array.isArray(obj)) {
        obj.forEach(clampIntegerBounds)
        return
    }
    const type = obj.type
    const isInteger = type === 'integer' || (Array.isArray(type) && type.includes('integer'))
    if (isInteger) {
        for (const key of INTEGER_BOUND_KEYS) {
            const value = obj[key]
            if (typeof value !== 'number') {
                continue
            }
            if (value > INT32_MAX) {
                obj[key] = INT32_MAX
            } else if (value < INT32_MIN) {
                obj[key] = INT32_MIN
            }
        }
    }
    for (const value of Object.values(obj)) {
        clampIntegerBounds(value)
    }
}

/**
 * Run standard preprocessing on a full OpenAPI schema.
 * Mutates the schema in place, also returns it for convenience.
 */
export function preprocessSchema(schema) {
    inlineSchemaRefs(schema)
    for (const name of SCHEMAS_TO_INLINE.keys()) {
        delete schema.components?.schemas?.[name]
    }
    stripCollidingInlineEnums(schema)
    clampIntegerBounds(schema)
    return schema
}
