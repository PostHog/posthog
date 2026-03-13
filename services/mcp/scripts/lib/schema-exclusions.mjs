/**
 * Applies nested field exclusions to an OpenAPI spec before Orval runs.
 *
 * Supports dot-notation paths for nested field removal:
 *   - `steps.*.selector_regex` — for each item in the `steps` array, remove `selector_regex`
 *   - `steps.*.properties.*.value` — nested arrays
 *   - `*` navigates into array `items`; regular segments navigate into `properties[segment]`
 *   - `$ref` is resolved transparently at each step
 *
 * Mutates the spec in place.
 */

/**
 * Resolve a $ref string to the corresponding schema object.
 * Only handles local component references (#/components/schemas/...).
 */
function resolveRef(spec, schema) {
    if (schema?.$ref) {
        const name = schema.$ref.replace('#/components/schemas/', '')
        return spec.components?.schemas?.[name]
    }
    return schema
}

/**
 * Walk a dotted path through an OpenAPI schema, resolving $ref at each step,
 * and delete the final segment from `properties` (updating `required` too).
 */
function excludePath(spec, schema, segments) {
    if (!schema || typeof schema !== 'object' || segments.length === 0) {
        return
    }

    schema = resolveRef(spec, schema)
    if (!schema) {
        return
    }

    const [head, ...tail] = segments

    if (tail.length === 0) {
        // Last segment — delete the property
        if (schema.properties?.[head]) {
            delete schema.properties[head]
            if (Array.isArray(schema.required)) {
                schema.required = schema.required.filter((r) => r !== head)
                if (schema.required.length === 0) {
                    delete schema.required
                }
            }
        }
        return
    }

    if (head === '*') {
        // Navigate into array items
        const items = resolveRef(spec, schema.items)
        if (items) {
            excludePath(spec, items, tail)
        }
        return
    }

    // Navigate into a named property
    const child = schema.properties?.[head]
    if (child) {
        excludePath(spec, resolveRef(spec, child), tail)
    }
}

/**
 * Find the request body schema for a given operationId.
 */
function findRequestBodySchema(spec, operationId) {
    for (const methods of Object.values(spec.paths ?? {})) {
        for (const operation of Object.values(methods)) {
            if (operation?.operationId !== operationId) {
                continue
            }
            const jsonContent = operation.requestBody?.content?.['application/json']
            if (jsonContent?.schema) {
                return resolveRef(spec, jsonContent.schema)
            }
        }
    }
    return undefined
}

/**
 * Apply field exclusions to the OpenAPI spec before Orval runs.
 *
 * Handles both top-level field names (`deleted`) and dotted paths
 * (`steps.*.selector_regex`). Walks each path through the operation's
 * request body schema, resolving $ref transparently — so changes to
 * shared component schemas affect all references.
 *
 * @param {object} spec — full OpenAPI spec (mutated in place)
 * @param {Map<string, string[]>} operationExclusions — operationId → paths to exclude
 */
export function applyNestedExclusions(spec, operationExclusions) {
    for (const [operationId, paths] of operationExclusions) {
        const bodySchema = findRequestBodySchema(spec, operationId)
        if (!bodySchema) {
            continue
        }
        for (const dottedPath of paths) {
            const segments = dottedPath.split('.')
            excludePath(spec, bodySchema, segments)
        }
    }
}
