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
