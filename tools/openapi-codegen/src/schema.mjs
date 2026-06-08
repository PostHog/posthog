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

/**
 * List component schema names in a filtered OpenAPI slice.
 *
 * @param {object} filteredSchema
 * @param {{ nameSuffix?: string, include?: string[] }} [options]
 * @returns {string[]}
 */
export function discoverComponentSchemaNames(filteredSchema, { nameSuffix = '', include = [] } = {}) {
    const schemas = filteredSchema.components?.schemas ?? {}
    const discovered = Object.keys(schemas).filter((name) => name.endsWith(nameSuffix))
    return [...new Set([...discovered, ...include])]
        .filter((name) => schemas[name])
        .sort()
}

/**
 * Build an OpenAPI document with codegen-only GET operations — one per component schema.
 *
 * Orval's Zod client inlines nested $refs inside real operation response bodies, so a
 * polymorphic catalog response never yields standalone per-config schema exports.
 * Pointing each codegen op's 200 response at a top-level component $ref is the supported
 * way to get named Zod exports from Orval today.
 *
 * @param {object} options
 * @param {object} options.baseSchema - filtered OpenAPI slice (paths + components)
 * @param {string[]} options.schemaNames - component schema names to export
 * @param {string} [options.pathPrefix]
 * @param {string} [options.operationIdPrefix]
 * @param {string} [options.title]
 * @param {string} [options.responseDescription]
 * @returns {object}
 */
export function buildCodegenSchemaResponseDoc({
    baseSchema,
    schemaNames,
    pathPrefix = '/_codegen/schema',
    operationIdPrefix = 'codegen_schema',
    title,
    responseDescription = 'Codegen-only schema (not a real endpoint).',
}) {
    const availableSchemaNames = schemaNames.filter((name) => baseSchema.components?.schemas?.[name])
    if (availableSchemaNames.length === 0) {
        throw new Error(`No component schemas found for codegen: ${schemaNames.join(', ')}`)
    }

    return {
        openapi: baseSchema.openapi,
        info: {
            ...baseSchema.info,
            title: title ?? `${baseSchema.info?.title ?? 'API'} - codegen schemas`,
        },
        paths: Object.fromEntries(
            availableSchemaNames.map((schemaName) => [
                `${pathPrefix}/${schemaName}/`,
                {
                    get: {
                        operationId: `${operationIdPrefix}_${schemaName}_retrieve`,
                        responses: {
                            200: {
                                description: responseDescription,
                                content: {
                                    'application/json': {
                                        schema: { $ref: `#/components/schemas/${schemaName}` },
                                    },
                                },
                            },
                        },
                    },
                },
            ])
        ),
        components: baseSchema.components,
    }
}

function _resolveComponentSchema(schemas, ref) {
    if (typeof ref !== 'string' || !ref.startsWith('#/components/schemas/')) {
        return undefined
    }
    return schemas[ref.replace('#/components/schemas/', '')]
}

function _resolveSingletonWidgetType(schemas, widgetTypeProperty) {
    if (!widgetTypeProperty || typeof widgetTypeProperty !== 'object') {
        return undefined
    }
    if (widgetTypeProperty.$ref) {
        const enumSchema = _resolveComponentSchema(schemas, widgetTypeProperty.$ref)
        if (enumSchema?.enum?.length === 1) {
            return enumSchema.enum[0]
        }
    }
    if (Array.isArray(widgetTypeProperty.enum) && widgetTypeProperty.enum.length === 1) {
        return widgetTypeProperty.enum[0]
    }
    return undefined
}

function _resolveConfigSchemaName(schemas, configSchemaProperty) {
    if (!configSchemaProperty || typeof configSchemaProperty !== 'object') {
        return undefined
    }
    const ref = configSchemaProperty.$ref ?? configSchemaProperty.allOf?.[0]?.$ref
    if (typeof ref !== 'string') {
        return undefined
    }
    return ref.replace('#/components/schemas/', '')
}

/**
 * Map widget_type → sorted config property keys from per-type catalog entry OpenAPI schemas.
 *
 * @param {object} catalogSlice - output of filterSchemaByOperationIds for widget_catalog_retrieve
 * @returns {Record<string, string[]>}
 */
export function discoverWidgetConfigPropertyKeys(catalogSlice) {
    const schemas = catalogSlice.components?.schemas ?? {}
    const propertyKeysByWidgetType = {}

    for (const [schemaName, schema] of Object.entries(schemas)) {
        if (!schemaName.endsWith('CatalogEntryOpenApi') || !schema?.properties) {
            continue
        }
        const widgetType = _resolveSingletonWidgetType(schemas, schema.properties.widget_type)
        const configSchemaName = _resolveConfigSchemaName(schemas, schema.properties.config_schema)
        if (!widgetType || !configSchemaName) {
            continue
        }
        const configSchema = schemas[configSchemaName]
        propertyKeysByWidgetType[widgetType] = Object.keys(configSchema?.properties ?? {}).sort()
    }

    return propertyKeysByWidgetType
}
