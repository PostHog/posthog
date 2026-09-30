/** Serialized size cap the config API applies to a scout's record schema. */
export const SCOUT_STRUCTURED_OUTPUT_SCHEMA_MAX_BYTES = 20000

export interface ScoutStructuredOutputSchemaParse {
    /** The parsed schema, or null when the text is blank or invalid. */
    schema: Record<string, unknown> | null
    /** What is wrong with the text, in the words shown under the editor. */
    error: string | null
}

// Positions the config API walks without reading their keys as JSON Schema keywords: a record
// property may legitimately be named `pattern`, and an example payload may contain any key.
const NAME_MAP_KEYS = ['properties', '$defs', 'definitions', 'dependentSchemas']
const DATA_KEYS = ['default', 'const', 'enum', 'examples']
const REFERENCE_KEYS = ['$ref', '$dynamicRef', '$recursiveRef']
const REGEX_KEYWORDS = ['pattern', 'patternProperties']

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function unsupportedConstructError(node: unknown): string | null {
    if (Array.isArray(node)) {
        for (const item of node) {
            const error = unsupportedConstructError(item)
            if (error) {
                return error
            }
        }
        return null
    }
    if (!isPlainObject(node)) {
        return null
    }
    for (const [key, value] of Object.entries(node)) {
        if (DATA_KEYS.includes(key)) {
            continue
        }
        if (NAME_MAP_KEYS.includes(key) && isPlainObject(value)) {
            for (const subSchema of Object.values(value)) {
                const error = unsupportedConstructError(subSchema)
                if (error) {
                    return error
                }
            }
            continue
        }
        if (REFERENCE_KEYS.includes(key) && typeof value === 'string' && !value.startsWith('#')) {
            return `The schema can only reference itself, so "${key}" must start with #.`
        }
        if (REGEX_KEYWORDS.includes(key)) {
            return `The schema can't use "${key}". Use enum, type, length, or numeric bounds instead.`
        }
        const error = unsupportedConstructError(value)
        if (error) {
            return error
        }
    }
    return null
}

/**
 * Read the editor text as a record schema, applying the rules the config API applies, so a
 * malformed schema is named under the field rather than coming back as a rejected save.
 * Blank text is a half-finished edit, not a clear: it parses to no schema and no error.
 */
export function parseScoutStructuredOutputSchema(text: string): ScoutStructuredOutputSchemaParse {
    const trimmed = text.trim()
    if (!trimmed) {
        return { schema: null, error: null }
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(trimmed)
    } catch {
        return { schema: null, error: 'This is not valid JSON.' }
    }
    if (!isPlainObject(parsed) || Object.keys(parsed).length === 0) {
        return { schema: null, error: 'The schema must be a JSON object with at least one key.' }
    }
    if (parsed.type !== 'object') {
        return { schema: null, error: 'The schema must set "type": "object" at its root.' }
    }
    if (new TextEncoder().encode(JSON.stringify(parsed)).length > SCOUT_STRUCTURED_OUTPUT_SCHEMA_MAX_BYTES) {
        return {
            schema: null,
            error: `The schema is over the ${SCOUT_STRUCTURED_OUTPUT_SCHEMA_MAX_BYTES} byte limit. Describe fewer fields.`,
        }
    }
    const constructError = unsupportedConstructError(parsed)
    if (constructError) {
        return { schema: null, error: constructError }
    }
    return { schema: parsed, error: null }
}

/** The record's field names, for the collapsed header. Empty when the schema names none. */
export function scoutStructuredOutputFieldNames(schema: Record<string, unknown> | null | undefined): string[] {
    const properties = schema?.properties
    return isPlainObject(properties) ? Object.keys(properties) : []
}
