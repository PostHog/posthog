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

function _isNullOpenApiSchema(schema) {
    return schema?.type === 'null' || (Array.isArray(schema?.type) && schema.type.length === 1 && schema.type[0] === 'null')
}

function _substantiveAnyOfArms(schema) {
    const arms = schema?.anyOf ?? schema?.oneOf
    if (!Array.isArray(arms)) {
        return []
    }
    return arms.filter((arm) => !_isNullOpenApiSchema(arm))
}

function _derefOpenApiSchema(schemas, schema) {
    if (!schema || typeof schema !== 'object') {
        return undefined
    }
    if (schema.$ref) {
        return _resolveComponentSchema(schemas, schema.$ref)
    }
    if (Array.isArray(schema.allOf) && schema.allOf.length > 0) {
        return _derefOpenApiSchema(schemas, schema.allOf[0])
    }

    const substantiveArms = _substantiveAnyOfArms(schema)
    if (substantiveArms.length === 1) {
        return _derefOpenApiSchema(schemas, substantiveArms[0])
    }
    if (substantiveArms.length > 1) {
        const objectArm = substantiveArms.find(
            (arm) => arm?.$ref || arm?.properties || arm?.type === 'object' || arm?.additionalProperties
        )
        if (objectArm) {
            return _derefOpenApiSchema(schemas, objectArm)
        }
        const enumArm = substantiveArms.find((arm) => Array.isArray(arm?.enum))
        if (enumArm) {
            return enumArm
        }
    }

    return schema
}

/**
 * Recursive OpenAPI property tree for parity checks (objects expand, enums/primitives leaf).
 *
 * @param {object|string} schemaOrRef - schema object, $ref object, or component name
 * @param {Record<string, object>} schemas - components.schemas
 * @param {Set<string>} [visited]
 * @returns {unknown}
 */
export function collectOpenApiPropertyTree(schemaOrRef, schemas, visited = new Set()) {
    let schema = schemaOrRef
    if (typeof schemaOrRef === 'string') {
        if (visited.has(schemaOrRef)) {
            return { $ref: schemaOrRef }
        }
        visited.add(schemaOrRef)
        schema = schemas[schemaOrRef]
    } else if (schemaOrRef?.$ref) {
        const componentName = schemaOrRef.$ref.replace('#/components/schemas/', '')
        if (visited.has(componentName)) {
            return { $ref: componentName }
        }
        visited.add(componentName)
        schema = schemas[componentName]
    } else {
        schema = _derefOpenApiSchema(schemas, schemaOrRef)
    }

    if (!schema || typeof schema !== 'object') {
        return { $type: 'unknown' }
    }

    if (Array.isArray(schema.enum)) {
        return { $enum: [...schema.enum].sort() }
    }

    const substantiveArms = _substantiveAnyOfArms(schema)
    const hasStringArm = substantiveArms.some((arm) => arm?.type === 'string')
    const hasArrayArm = substantiveArms.some((arm) => arm?.type === 'array')
    if (hasStringArm && hasArrayArm) {
        return { $types: ['string'] }
    }

    const primitiveTypes = substantiveArms
        .map((arm) => arm?.type)
        .filter((type) => typeof type === 'string' && type !== 'null')
    if (primitiveTypes.length > 1) {
        return { $types: [...new Set(primitiveTypes)].sort() }
    }
    if (primitiveTypes.length === 1) {
        return { $type: primitiveTypes[0] }
    }

    if (schema.properties && typeof schema.properties === 'object') {
        const tree = {}
        for (const [key, propertySchema] of Object.entries(schema.properties)) {
            tree[key] = collectOpenApiPropertyTree(propertySchema, schemas, new Set(visited))
        }
        return tree
    }

    if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        return {
            $record: collectOpenApiPropertyTree(schema.additionalProperties, schemas, new Set(visited)),
        }
    }

    if (schema.type === 'array' && schema.items) {
        return { $array: collectOpenApiPropertyTree(schema.items, schemas, new Set(visited)) }
    }

    if (schema.type) {
        return { $type: schema.type }
    }

    return { $type: 'unknown' }
}

/**
 * Map catalog entry schemas → config property metadata keyed by a type discriminator field.
 *
 * @param {object} catalogSlice - output of filterSchemaByOperationIds on a catalog op
 * @param {{
 *   entrySuffix?: string,
 *   typeField?: string,
 *   configField?: string,
 *   includePropertyTrees?: boolean,
 * }} [options]
 * @returns {{ propertyKeys: Record<string, string[]>, propertyTrees?: Record<string, unknown> }}
 */
export function discoverCatalogEntryConfigPropertyKeys(
    catalogSlice,
    {
        entrySuffix = 'CatalogEntryOpenApi',
        typeField = 'widget_type',
        configField = 'config_schema',
        includePropertyTrees = false,
    } = {}
) {
    const schemas = catalogSlice.components?.schemas ?? {}
    const propertyKeys = {}
    const propertyTrees = includePropertyTrees ? {} : undefined

    for (const [schemaName, schema] of Object.entries(schemas)) {
        if (!schemaName.endsWith(entrySuffix) || !schema?.properties) {
            continue
        }
        const widgetType = _resolveSingletonWidgetType(schemas, schema.properties[typeField])
        const configSchemaName = _resolveConfigSchemaName(schemas, schema.properties[configField])
        if (!widgetType || !configSchemaName) {
            continue
        }
        const configSchema = schemas[configSchemaName]
        propertyKeys[widgetType] = Object.keys(configSchema?.properties ?? {}).sort()
        if (propertyTrees) {
            propertyTrees[widgetType] = collectOpenApiPropertyTree(configSchemaName, schemas)
        }
    }

    return propertyTrees ? { propertyKeys, propertyTrees } : { propertyKeys }
}
