/**
 * Applies nested field exclusions to an OpenAPI spec before Orval runs.
 *
 * Supports dot-notation paths for nested field removal:
 *   - `steps.*.selector_regex` — for each item in the `steps` array, remove `selector_regex`
 *   - `steps.*.properties.*.value` — nested arrays
 *   - `*` navigates into array `items`; regular segments navigate into `properties[segment]`
 *   - `$ref` is resolved via clone-on-write: shared component schemas are never mutated
 *
 * Mutates the operation's schema subtree in place, but leaves shared
 * component schemas (`#/components/schemas/...`) untouched.
 */

function isUnsafeKey(key) {
    return key === '__proto__' || key === 'constructor' || key === 'prototype'
}

/**
 * If `schema` is a `$ref`, deep-clone the referenced component and return it.
 * Otherwise return `schema` unchanged.
 */
function cloneIfRef(spec, schema) {
    if (schema?.$ref) {
        const name = schema.$ref.replace('#/components/schemas/', '')
        const original = spec.components?.schemas?.[name]
        return original ? JSON.parse(JSON.stringify(original)) : undefined
    }
    return schema
}

/**
 * Walk a dotted path through an OpenAPI schema and delete the final segment
 * from `properties` (updating `required` too).
 *
 * Uses clone-on-write: when a `$ref` is encountered, the referenced component
 * is deep-cloned and the parent's reference is replaced with the clone before
 * any mutation. This ensures shared component schemas are never modified.
 *
 * @param {object} spec — full OpenAPI spec
 * @param {object} parentObj — the object that owns the current schema value
 * @param {string} parentKey — the key within `parentObj` that holds the schema
 * @param {string[]} segments — remaining path segments to navigate
 */
function excludePath(spec, parentObj, parentKey, segments) {
    if (segments.length === 0) {
        return
    }

    let schema = parentObj[parentKey]
    if (!schema || typeof schema !== 'object') {
        return
    }

    // Clone-on-write: if this is a $ref, replace with a deep copy before mutating
    if (schema.$ref) {
        schema = cloneIfRef(spec, schema)
        if (!schema) {
            return
        }
        parentObj[parentKey] = schema
    }

    const [head, ...tail] = segments

    if (isUnsafeKey(head)) {
        return
    }

    if (tail.length === 0) {
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
        if (schema.items) {
            excludePath(spec, schema, 'items', tail)
        }
        return
    }

    if (schema.properties?.[head]) {
        excludePath(spec, schema.properties, head, tail)
    }
}

/**
 * Find the request body's `{ parent, key }` reference for a given operationId,
 * so callers can pass it to `excludePath` for clone-on-write.
 */
function findRequestBodySchemaRef(spec, operationId) {
    for (const methods of Object.values(spec.paths ?? {})) {
        for (const operation of Object.values(methods)) {
            if (operation?.operationId !== operationId) {
                continue
            }
            const jsonContent = operation.requestBody?.content?.['application/json']
            if (jsonContent?.schema) {
                return { parent: jsonContent, key: 'schema' }
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
 * request body schema, cloning any `$ref` targets before mutation so
 * that shared component schemas are never modified.
 *
 * @param {object} spec — full OpenAPI spec (mutated in place per-operation)
 * @param {Map<string, string[]>} operationExclusions — operationId → paths to exclude
 */
export function applyNestedExclusions(spec, operationExclusions) {
    for (const [operationId, paths] of operationExclusions) {
        const ref = findRequestBodySchemaRef(spec, operationId)
        if (!ref) {
            continue
        }
        for (const dottedPath of paths) {
            const segments = dottedPath.split('.')
            excludePath(spec, ref.parent, ref.key, segments)
        }
    }
}
