/**
 * OpenAPI schema transforms applied before Orval codegen.
 *
 * These fix known drf-spectacular quirks that produce incorrect Zod output.
 */

/**
 * Strip `minLength` from string schemas that have an `enum` constraint.
 * drf-spectacular adds `minLength: 1` to ChoiceField (which inherits CharField),
 * but it's redundant when `enum` already constrains the values.
 * Orval translates this into `.min(1).enum([...])` which is incorrect for enums.
 */
export function stripEnumMinLength(obj) {
    if (!obj || typeof obj !== 'object') {
        return
    }
    if (obj.enum && obj.minLength !== undefined) {
        delete obj.minLength
    }
    for (const value of Object.values(obj)) {
        stripEnumMinLength(value)
    }
}

/**
 * Strip `format: "uuid"` from all string schemas.
 * Zod 4's `.uuid()` enforces strict RFC 4122 version/variant bits, which some
 * PostHog UUID generation paths don't satisfy (e.g. provider key ids with a
 * `-0000-` version group). These are request/response schemas, so there's no
 * value in re-validating the UUID format client-side.
 *
 * Nullable fields (allow_null=True) serialize as `type: ["string", "null"]`,
 * so match both the scalar and array forms.
 */
export function stripUuidFormat(obj) {
    if (!obj || typeof obj !== 'object') {
        return
    }
    const isStringType = obj.type === 'string' || (Array.isArray(obj.type) && obj.type.includes('string'))
    if (isStringType && obj.format === 'uuid') {
        delete obj.format
    }
    for (const value of Object.values(obj)) {
        stripUuidFormat(value)
    }
}

/**
 * Replace Orval's unconstrained-value schema with Zod's recursive JSON schema.
 *
 * `zod.unknown()` is emitted for OpenAPI values whose shape is intentionally
 * unconstrained. It serializes to an untyped JSON Schema node, so MCP clients
 * do not learn that they may send structured JSON and commonly stringify
 * objects or arrays before invoking the tool. `zod.json()` preserves the same
 * JSON-transportable values while advertising the object and array branches.
 *
 * This operates on Orval's generated TypeScript source rather than changing
 * the OpenAPI document: the source schema is still accurately unconstrained,
 * and the conversion is specific to MCP's JSON tool-input contract.
 */
export function useJsonSchemaForUnconstrainedValues(generatedSource) {
    return generatedSource.replace(/\bzod\.unknown\(\)/g, 'zod.json()')
}
