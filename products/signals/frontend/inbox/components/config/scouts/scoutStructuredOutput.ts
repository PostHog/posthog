/** Serialized size cap the config API applies to a scout's record schema. */
export const SCOUT_STRUCTURED_OUTPUT_SCHEMA_MAX_BYTES = 20000

export interface ScoutStructuredOutputSchemaParse {
    /** The parsed schema, or null when the text is blank or invalid. */
    schema: Record<string, unknown> | null
    /** What is wrong with the text, in the words shown under the editor. */
    error: string | null
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * The byte count the API compares with the cap. The API measures Python's default `json.dumps`,
 * which puts a space after every `,` and `:` and writes each UTF-16 code unit outside printable
 * ASCII as a 6-byte `\uXXXX` escape. Compact UTF-8 counts fewer bytes, so it lets through schemas
 * the API refuses.
 */
function apiSerializedByteLength(value: unknown): number {
    const json = JSON.stringify(value)
    let bytes = json.length
    let inString = false
    for (let index = 0; index < json.length; index++) {
        const char = json[index]
        if (inString) {
            if (char === '\\') {
                // Every escape JSON.stringify writes is ASCII, and Python writes one of the same length.
                index++
            } else if (char === '"') {
                inString = false
            } else if (char > '~') {
                bytes += 5
            }
        } else if (char === '"') {
            inString = true
        } else if (char === ',' || char === ':') {
            bytes += 1
        }
    }
    return bytes
}

/**
 * Read the editor text as a record schema, applying the shape rules the config API applies, so a
 * malformed schema is named under the field rather than coming back as a rejected save. The API
 * also refuses schema constructs that would attack the worker, such as a reference to another
 * document or a regex keyword. Those rules stay on the server alone, because a copy here can only
 * drift, and a copy that drifts toward strict refuses a schema the API accepts. The save surfaces
 * the API's own message for them.
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
    if (apiSerializedByteLength(parsed) > SCOUT_STRUCTURED_OUTPUT_SCHEMA_MAX_BYTES) {
        return {
            schema: null,
            error: `The schema is over the ${SCOUT_STRUCTURED_OUTPUT_SCHEMA_MAX_BYTES} byte limit. Describe fewer fields.`,
        }
    }
    return { schema: parsed, error: null }
}

/** The record's field names, for the collapsed header. Empty when the schema names none. */
export function scoutStructuredOutputFieldNames(schema: Record<string, unknown> | null | undefined): string[] {
    const properties = schema?.properties
    return isPlainObject(properties) ? Object.keys(properties) : []
}
