/**
 * OpenAPI schema traversal and filtering utilities.
 *
 * These functions operate on raw OpenAPI schema objects and have no
 * knowledge of any specific product or code generator.
 */

/**
 * Collect all $ref strings from an OpenAPI object (recursive).
 */
export function collectSchemaRefs(obj, refs = new Set()) {
    if (!obj || typeof obj !== 'object') {
        return refs
    }
    if (obj.$ref && typeof obj.$ref === 'string') {
        refs.add(obj.$ref)
    }
    for (const value of Object.values(obj)) {
        collectSchemaRefs(value, refs)
    }
    return refs
}

/**
 * Iteratively resolve transitive $refs until no new ones are found.
 *
 * @param {Record<string, unknown>} schemas - components.schemas from the OpenAPI spec
 * @param {Set<string>} refs - initial set of $ref strings (e.g. '#/components/schemas/Foo')
 * @returns {Set<string>} all refs including transitive dependencies
 */
export function resolveNestedRefs(schemas, refs) {
    const allRefs = new Set(refs)
    let changed = true
    while (changed) {
        changed = false
        for (const ref of allRefs) {
            const schemaName = ref.replace('#/components/schemas/', '')
            const schema = schemas[schemaName]
            if (schema) {
                for (const nestedRef of collectSchemaRefs(schema)) {
                    if (!allRefs.has(nestedRef)) {
                        allRefs.add(nestedRef)
                        changed = true
                    }
                }
            }
        }
    }
    return allRefs
}

/**
 * Filter a full OpenAPI schema to only the paths matching the given operationIds,
 * pulling in all transitively referenced component schemas.
 *
 * @param {object} fullSchema - complete OpenAPI schema object
 * @param {Set<string>} operationIds - operationIds to include
 * @returns {object} filtered OpenAPI schema
 */
export function filterSchemaByOperationIds(fullSchema, operationIds) {
    const httpMethods = new Set(['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'])
    const filteredPaths = {}
    const refs = new Set()

    for (const [pathKey, operations] of Object.entries(fullSchema.paths ?? {})) {
        for (const [method, operation] of Object.entries(operations ?? {})) {
            if (!httpMethods.has(method)) {
                continue
            }
            if (!operationIds.has(operation.operationId)) {
                continue
            }
            filteredPaths[pathKey] ??= {}
            filteredPaths[pathKey][method] = operation
            collectSchemaRefs(operation, refs)
        }
    }

    const allSchemas = fullSchema.components?.schemas ?? {}
    const allRefs = resolveNestedRefs(allSchemas, refs)
    const filteredSchemas = {}

    for (const ref of allRefs) {
        const schemaName = ref.replace('#/components/schemas/', '')
        if (allSchemas[schemaName]) {
            filteredSchemas[schemaName] = allSchemas[schemaName]
        }
    }

    return {
        openapi: fullSchema.openapi,
        info: { ...fullSchema.info, title: `${fullSchema.info?.title ?? 'API'} - ${operationIds.size} ops` },
        paths: filteredPaths,
        components: { schemas: filteredSchemas },
    }
}
