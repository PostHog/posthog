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
 * @param {{ includeResponseSchemas?: boolean }} [options] - filtering options
 * @returns {object} filtered OpenAPI schema
 */
export function filterSchemaByOperationIds(fullSchema, operationIds, options = {}) {
    const { includeResponseSchemas = true } = options
    const httpMethods = new Set(['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'])
    const filteredPaths = {}
    const refs = new Set()

    const stripOperationResponses = (operation) => {
        if (
            !operation ||
            typeof operation !== 'object' ||
            !operation.responses ||
            typeof operation.responses !== 'object'
        ) {
            return operation
        }

        const responses = {}
        for (const [statusCode, response] of Object.entries(operation.responses)) {
            if (response && typeof response === 'object' && !('$ref' in response)) {
                responses[statusCode] = {
                    description: typeof response.description === 'string' ? response.description : '',
                }
            } else {
                responses[statusCode] = { description: '' }
            }
        }

        return {
            ...operation,
            responses,
        }
    }

    for (const [pathKey, operations] of Object.entries(fullSchema.paths ?? {})) {
        for (const [method, operation] of Object.entries(operations ?? {})) {
            if (!httpMethods.has(method)) {
                continue
            }
            if (!operationIds.has(operation.operationId)) {
                continue
            }
            const filteredOperation = includeResponseSchemas ? operation : stripOperationResponses(operation)
            filteredPaths[pathKey] ??= {}
            filteredPaths[pathKey][method] = filteredOperation
            collectSchemaRefs(filteredOperation, refs)
        }
    }

    const allSchemas = fullSchema.components?.schemas ?? {}
    const allParameters = fullSchema.components?.parameters ?? {}

    // Pull in referenced parameter components first — operations may use $ref to shared
    // path/query parameters defined in components.parameters (e.g. ProjectIdPath). Each
    // parameter definition can in turn reference component schemas via its inner ``schema``,
    // so we collect those refs and feed them into the schema resolution below.
    const filteredParameters = {}
    // Set iteration visits items added mid-loop (insertion-order); schema refs
    // added by collectSchemaRefs are skipped here by the startsWith guard and
    // picked up by resolveNestedRefs below.
    for (const ref of refs) {
        if (!ref.startsWith('#/components/parameters/')) {
            continue
        }
        const paramName = ref.replace('#/components/parameters/', '')
        const paramDef = allParameters[paramName]
        if (paramDef) {
            filteredParameters[paramName] = paramDef
            collectSchemaRefs(paramDef, refs)
        }
    }

    const allRefs = resolveNestedRefs(allSchemas, refs)
    const filteredSchemas = {}

    for (const ref of allRefs) {
        const schemaName = ref.replace('#/components/schemas/', '')
        if (allSchemas[schemaName]) {
            filteredSchemas[schemaName] = allSchemas[schemaName]
        }
    }

    const components = { schemas: filteredSchemas }
    if (Object.keys(filteredParameters).length > 0) {
        components.parameters = filteredParameters
    }

    return {
        openapi: fullSchema.openapi,
        info: { ...fullSchema.info, title: `${fullSchema.info?.title ?? 'API'} - ${operationIds.size} ops` },
        paths: filteredPaths,
        components,
    }
}
