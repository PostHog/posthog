import { findOperation, resolveDocumentation } from './agent-operations.mjs'

export function pascalCase(value) {
    return value.replace(/(^|[-_.])([a-z])/g, (_, _separator, letter) => letter.toUpperCase())
}

export function annotateDocumentation(value, source, pointer = '#') {
    if (!value || typeof value !== 'object') {
        return
    }
    for (const [key, child] of Object.entries(value)) {
        annotateDocumentation(child, source, `${pointer}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`)
    }
    if (typeof value.description === 'string' && !value['x-documentation-source']) {
        value['x-documentation-source'] = { ...source, pointer }
    }
}

export function resolveRef(spec, schema, seen = new Set()) {
    if (!schema?.$ref) {
        return schema
    }
    const ref = schema.$ref
    if (!ref.startsWith('#/') || seen.has(ref)) {
        throw new Error(`Cannot resolve schema reference ${ref}`)
    }
    const target = ref
        .slice(2)
        .split('/')
        .reduce((node, key) => node?.[key.replace(/~1/g, '/').replace(/~0/g, '~')], spec)
    if (!target) {
        throw new Error(`Missing schema reference ${ref}`)
    }
    const { $ref, ...siblings } = schema
    return { ...resolveRef(spec, target, new Set([...seen, ref])), ...siblings }
}

export function objectSchema(spec, node) {
    const schema = resolveRef(spec, node)
    if (!schema?.allOf) {
        return schema
    }
    const { allOf, ...base } = schema
    if (allOf.length === 1 && !base.properties) {
        return { ...objectSchema(spec, allOf[0]), ...base }
    }
    const parts = [...allOf.map((part) => objectSchema(spec, part)), base]
    if (parts.some((part) => part.oneOf || part.anyOf || (part.type && part.type !== 'object'))) {
        throw new Error('Object composition with union or scalar branches needs an SDK adapter')
    }
    const properties = {}
    for (const part of parts) {
        for (const [key, value] of Object.entries(part.properties ?? {})) {
            if (properties[key] && JSON.stringify(properties[key]) !== JSON.stringify(value)) {
                throw new Error(`Conflicting allOf property ${key} needs an SDK adapter`)
            }
            properties[key] = value
        }
    }
    return {
        ...Object.assign({}, ...parts),
        type: 'object',
        properties,
        required: [...new Set(parts.flatMap((part) => part.required ?? []))],
    }
}

/** Shape the schema with the same dotted paths that shape the runtime response. */
export function projectSchema(spec, node, paths, mode, selectable = false) {
    let schema = objectSchema(spec, node)
    if (!paths?.length) {
        return schema
    }
    if (Array.isArray(schema.type)) {
        const { type, ...rest } = schema
        schema = { anyOf: type.map((value) => ({ ...rest, type: value })) }
    }
    if (schema.anyOf || schema.oneOf) {
        const kind = schema.anyOf ? 'anyOf' : 'oneOf'
        return {
            ...schema,
            [kind]: schema[kind].map((variant) => projectSchema(spec, variant, paths, mode, selectable)),
        }
    }
    if (schema.type === 'array') {
        if (paths.some((value) => !value.startsWith('*.'))) {
            throw new Error('Array projection paths must start with *.')
        }
        return {
            ...schema,
            items: projectSchema(
                spec,
                schema.items,
                paths.map((value) => value.slice(2)),
                mode,
                selectable
            ),
        }
    }
    if (!schema.properties) {
        if (schema.type === 'null') {
            return schema
        }
        if (mode === 'exclude' && (!schema.type || schema.type === 'object')) {
            return schema
        }
        throw new Error(`Cannot project fields from an unstructured schema: ${paths.join(', ')}`)
    }
    const groups = new Map()
    for (const value of paths) {
        const [key, ...tail] = value.split('.')
        if (!(key in schema.properties)) {
            if (mode === 'exclude') {
                continue
            }
            throw new Error(`Projection field ${value} is absent from its source schema`)
        }
        if (!groups.has(key)) {
            groups.set(key, [])
        }
        groups.get(key).push(tail.join('.'))
    }
    const properties = mode === 'include' ? {} : { ...schema.properties }
    for (const [key, tails] of groups) {
        if (tails.includes('')) {
            if (mode === 'include') {
                properties[key] = schema.properties[key]
            } else {
                delete properties[key]
            }
        } else {
            properties[key] = projectSchema(spec, schema.properties[key], tails, mode, selectable)
        }
    }
    return {
        ...schema,
        properties,
        required: selectable ? [] : (schema.required ?? []).filter((key) => Object.hasOwn(properties, key)),
        ...(mode === 'include' ? { additionalProperties: false } : {}),
    }
}

const JSON_SCHEMAS = {
    JsonObject: { type: 'object', additionalProperties: { $ref: '#/components/schemas/JsonValue' } },
    JsonValue: {
        anyOf: [
            { type: 'string' },
            { type: 'number' },
            { type: 'boolean' },
            { type: 'null' },
            { $ref: '#/components/schemas/JsonObject' },
            { type: 'array', items: { $ref: '#/components/schemas/JsonValue' } },
        ],
    },
    ResponseMeta: {
        type: 'object',
        properties: { status: { type: 'integer' }, requestId: { type: 'string' } },
        required: ['status'],
    },
}

function validationSchema(schema) {
    if (!schema || typeof schema !== 'object') {
        return schema
    }
    const result = Object.fromEntries(
        Object.entries(schema).filter(
            ([key]) =>
                !key.startsWith('x-') && !['description', 'title', 'example', 'examples', 'deprecated'].includes(key)
        )
    )
    for (const key of ['properties', 'patternProperties', '$defs']) {
        if (result[key]) {
            result[key] = Object.fromEntries(
                Object.entries(result[key]).map(([name, value]) => [name, validationSchema(value)])
            )
        }
    }
    for (const key of ['items', 'additionalProperties', 'not']) {
        if (result[key]) {
            result[key] = validationSchema(result[key])
        }
    }
    for (const key of ['anyOf', 'oneOf', 'allOf']) {
        if (result[key]) {
            result[key] = result[key].map(validationSchema)
        }
    }
    return result
}

/** Operation-local registries prevent a projection or PATCH override changing another method's schema. */
export class SchemaRegistry {
    constructor(spec, prefix) {
        this.spec = spec
        this.prefix = prefix
        this.schemas = structuredClone(JSON_SCHEMAS)
        this.refs = new Map()
    }

    normalize(node, name, direction, { patch = false, stripNulls = false, nullOptional = false } = {}) {
        if (node === false) {
            return false
        }
        if (node === true || !node || Object.keys(node).length === 0) {
            return { $ref: '#/components/schemas/JsonValue' }
        }
        if (patch && Object.hasOwn(node, 'default')) {
            node = { ...node }
            delete node.default
        }
        if (node.nullable) {
            const { nullable, ...value } = node
            return this.normalize(
                { anyOf: [value, { type: 'null' }], ...(value.description ? { description: value.description } : {}) },
                name,
                direction,
                { patch, stripNulls, nullOptional }
            )
        }
        if (node.$ref) {
            if (
                node.$ref.startsWith('#/components/schemas/') &&
                Object.hasOwn(JSON_SCHEMAS, node.$ref.split('/').at(-1)) &&
                !this.spec.components?.schemas?.[node.$ref.split('/').at(-1)]
            ) {
                return node
            }
            const key = `${direction}:${patch}:${stripNulls}:${nullOptional}:${node.$ref}`
            let targetName = this.refs.get(key)
            if (!targetName) {
                targetName = `${this.prefix}${direction === 'input' ? 'Request' : 'Response'}${pascalCase(node.$ref.split('/').at(-1))}${stripNulls ? 'WithoutNulls' : ''}${nullOptional ? 'NullableFields' : ''}`
                this.refs.set(key, targetName)
                this.schemas[targetName] = {}
                this.schemas[targetName] = this.normalize(
                    resolveRef(this.spec, { $ref: node.$ref }),
                    targetName,
                    direction,
                    { patch, stripNulls, nullOptional }
                )
            }
            const { $ref, ...siblings } = node
            return { $ref: `#/components/schemas/${targetName}`, ...siblings }
        }
        let schema = structuredClone(objectSchema(this.spec, node))
        delete schema.$schema
        delete schema.$defs
        delete schema.definitions
        if (typeof schema.deprecated === 'string') {
            schema.description = `${schema.description ?? ''}\n\n@deprecated ${schema.deprecated}`.trim()
            schema.deprecated = true
        }
        if (Array.isArray(schema.type)) {
            const { type, ...rest } = schema
            schema = { ...rest, anyOf: type.map((value) => ({ ...rest, type: value })) }
            delete schema.properties
            delete schema.items
            delete schema.required
        }
        delete schema.discriminator
        delete schema.xml
        if (patch) {
            delete schema.default
        }
        for (const kind of ['anyOf', 'oneOf']) {
            if (schema[kind]) {
                schema[kind] = schema[kind].map((part, index) =>
                    this.normalize(part, `${name}Variant${index + 1}`, direction, { patch, stripNulls, nullOptional })
                )
            }
        }
        if (schema.properties || schema.type === 'object') {
            const properties = {}
            const removedNulls = new Set()
            for (const [key, raw] of Object.entries(schema.properties ?? {})) {
                const value = resolveRef(this.spec, raw)
                if ((direction === 'input' && value.readOnly) || (direction === 'output' && value.writeOnly)) {
                    continue
                }
                let property = raw
                if (
                    stripNulls &&
                    (value.nullable ||
                        value.type === 'null' ||
                        value.type?.includes?.('null') ||
                        [...(value.anyOf ?? []), ...(value.oneOf ?? [])].some((part) => part.type === 'null'))
                ) {
                    property = { ...value }
                    delete property.nullable
                    if (Array.isArray(property.type)) {
                        property.type = property.type.filter((type) => type !== 'null')
                    }
                    for (const kind of ['anyOf', 'oneOf']) {
                        if (property[kind]) {
                            property[kind] = property[kind].filter((part) => part.type !== 'null')
                        }
                    }
                    if (
                        property.type === 'null' ||
                        property.type?.length === 0 ||
                        property.anyOf?.length === 0 ||
                        property.oneOf?.length === 0
                    ) {
                        continue
                    }
                    removedNulls.add(key)
                }
                if (nullOptional && !stripNulls && !(schema.required ?? []).includes(key)) {
                    property = {
                        anyOf: [property, { type: 'null' }],
                        ...Object.fromEntries(
                            Object.entries(value).filter(
                                ([name]) =>
                                    name.startsWith('x-') || ['description', 'deprecated', 'readOnly'].includes(name)
                            )
                        ),
                    }
                }
                properties[key] = this.normalize(property, `${name}${pascalCase(key)}`, direction, {
                    patch,
                    stripNulls,
                    nullOptional,
                })
            }
            schema.properties = properties
            schema.type = 'object'
            schema.required = (schema.required ?? []).filter(
                (key) => Object.hasOwn(properties, key) && !removedNulls.has(key)
            )
            if (typeof schema.additionalProperties === 'object') {
                schema.additionalProperties = this.normalize(schema.additionalProperties, `${name}Value`, direction, {
                    patch,
                    stripNulls,
                    nullOptional,
                })
            }
            if (
                !Object.keys(properties).length &&
                schema.additionalProperties !== false &&
                schema.additionalProperties === undefined
            ) {
                schema.additionalProperties = { $ref: '#/components/schemas/JsonValue' }
            }
        }
        if (schema.items) {
            schema.items = this.normalize(schema.items, `${name}Item`, direction, { patch, stripNulls, nullOptional })
        }
        for (const key of ['propertyNames', 'contains', 'not', 'if', 'then', 'else', 'additionalItems']) {
            if (typeof schema[key] === 'object') {
                schema[key] = this.normalize(schema[key], `${name}${pascalCase(key)}`, direction, {
                    patch,
                    stripNulls,
                    nullOptional,
                })
            }
        }
        for (const key of ['patternProperties', 'dependentSchemas']) {
            if (schema[key]) {
                schema[key] = Object.fromEntries(
                    Object.entries(schema[key]).map(([field, value]) => [
                        field,
                        this.normalize(value, `${name}${pascalCase(field)}`, direction, {
                            patch,
                            stripNulls,
                            nullOptional,
                        }),
                    ])
                )
            }
        }
        if (schema.prefixItems) {
            schema.prefixItems = schema.prefixItems.map((value, index) =>
                this.normalize(value, `${name}Item${index + 1}`, direction, { patch, stripNulls, nullOptional })
            )
        }
        if (!schema.type && !schema.anyOf && !schema.oneOf && !schema.enum && !Object.hasOwn(schema, 'const')) {
            return { $ref: '#/components/schemas/JsonValue', ...schema }
        }
        return schema
    }

    add(name, schema, direction, options) {
        this.schemas[name] = this.normalize(objectSchema(this.spec, schema), name, direction, options)
        return { $ref: `#/components/schemas/${name}` }
    }

    runtime(rootName) {
        const schemas = {}
        const visit = (node) => {
            if (!node || typeof node !== 'object') {
                return
            }
            if (node.$ref?.startsWith('#/components/schemas/')) {
                const name = node.$ref.split('/').at(-1)
                if (!Object.hasOwn(schemas, name)) {
                    schemas[name] = this.schemas[name]
                    if (!schemas[name]) {
                        throw new Error(`Missing resolved schema ${name}`)
                    }
                    visit(schemas[name])
                }
            }
            for (const value of Object.values(node)) {
                visit(value)
            }
        }
        visit({ $ref: `#/components/schemas/${rootName}` })
        return JSON.parse(
            JSON.stringify({
                $ref: `#/components/schemas/${rootName}`,
                components: {
                    schemas: Object.fromEntries(
                        Object.entries(schemas).map(([name, schema]) => [name, validationSchema(schema)])
                    ),
                },
            })
        )
    }
}

function overrideDescription(schema, description, source) {
    if (!description) {
        return schema
    }
    return {
        ...schema,
        description,
        'x-override-source': source,
        ...(schema.description ? { 'x-source-description': schema.description } : {}),
    }
}

export function unsupportedReason(config, category, resolved) {
    for (const key of ['hooks', 'confirmed_action', 'input_schema', 'validators', 'required_when_set', 'soft_delete']) {
        if (config[key]) {
            return `${key} requires a direct API adapter`
        }
    }
    for (const key of ['feature_flag', 'feature_entitlement', 'requires_ai_consent', 'hidden_when_flag_on']) {
        if (config[key] || category[key]) {
            return `${key} requires an availability adapter`
        }
    }
    if (resolved?.operation['x-internal']) {
        return 'The endpoint is marked x-internal'
    }
    if (resolved?.path.includes('{organization_id}')) {
        return 'Organization-scoped operations need an organization client'
    }
    if (config.inject_body?.created_via === 'mcp') {
        return 'MCP attribution needs a direct API value'
    }
    for (const override of Object.values(config.param_overrides ?? {})) {
        if (override.input_schema || override.schema_ref || override.fallback) {
            return 'Custom parameter schemas or state fallbacks require an adapter'
        }
    }
    return undefined
}

export function resolveSdkOperation(spec, config, category, toolName, yamlFile, repoRoot) {
    const resolved = findOperation(spec, config.operation)
    if (!resolved) {
        throw new Error(`OpenAPI operation ${config.operation} is missing`)
    }
    const reason = unsupportedReason(config, category, resolved)
    if (reason) {
        throw new Error(`${toolName}: ${reason}`)
    }
    const { namespace, method } = config.sdk
    const prefix = `${pascalCase(namespace)}${pascalCase(method)}`
    const registry = new SchemaRegistry(spec, prefix)
    const operation = resolved.operation
    const input = { type: 'object', properties: {}, required: [], additionalProperties: false }
    const bindings = []
    const excluded = new Set(config.exclude_params ?? [])
    const included = config.include_params ? new Set(config.include_params) : null
    const keep = (name) => !excluded.has(name) && (!included || included.has(name))
    const add = (rawName, rawSchema, required, location, extras = {}) => {
        const name = config.rename_params?.[rawName] ?? rawName
        if (Object.hasOwn(input.properties, name)) {
            throw new Error(`Input parameter collision: ${name}`)
        }
        const override = config.param_overrides?.[rawName] ?? {}
        let schema = overrideDescription(resolveRef(spec, rawSchema), override.description, {
            kind: 'mcp_yaml',
            file: yamlFile.slice(repoRoot.length + 1),
            pointer: `/tools/${toolName}/param_overrides/${rawName}/description`,
        })
        if (Object.hasOwn(override, 'default') && resolved.method !== 'PATCH') {
            schema = { ...schema, default: override.default }
        }
        input.properties[name] = schema
        if ((required || override.required) && (resolved.method === 'PATCH' || !Object.hasOwn(override, 'default'))) {
            input.required.push(name)
        }
        bindings.push({ name, wireName: rawName, location, ...extras })
    }
    const pathParameters = spec.paths[resolved.path].parameters ?? []
    const params = new Map(
        [...pathParameters, ...(operation.parameters ?? [])].map((raw) => {
            const value = resolveRef(spec, raw)
            return [`${value.in}:${value.name}`, value]
        })
    )
    for (const parameter of params.values()) {
        if (parameter.name === 'project_id' && parameter.in === 'path') {
            continue
        }
        if (parameter.in === 'query' && (parameter.name === 'format' || !keep(parameter.name))) {
            continue
        }
        if (!['path', 'query'].includes(parameter.in)) {
            throw new Error(`Unsupported ${parameter.in} parameter ${parameter.name}`)
        }
        if (parameter.in === 'query' && parameter.style && parameter.style !== 'form') {
            throw new Error(`Unsupported query style ${parameter.style}`)
        }
        const parameterSchema = resolveRef(spec, parameter.schema)
        if (
            parameter.in === 'query' &&
            (parameter.content ||
                parameterSchema?.type === 'object' ||
                parameterSchema?.properties ||
                parameterSchema?.oneOf ||
                parameterSchema?.anyOf)
        ) {
            throw new Error(`Structured query parameter ${parameter.name} needs a serialization adapter`)
        }
        add(
            parameter.name,
            {
                ...parameter.schema,
                ...(parameter.description
                    ? {
                          description: parameter.description,
                          'x-documentation-source': parameter['x-documentation-source'],
                      }
                    : {}),
            },
            parameter.required || parameter.in === 'path',
            parameter.in,
            parameter.in === 'query' ? { explode: parameter.explode !== false } : {}
        )
    }
    const body = operation.requestBody ? resolveRef(spec, operation.requestBody) : undefined
    if (body) {
        const raw = body.content?.['application/json']?.schema
        if (!raw) {
            throw new Error('Only application/json request bodies are supported')
        }
        const schema = objectSchema(spec, raw)
        if (schema.oneOf || schema.anyOf || !schema.properties) {
            throw new Error('A non-object or union request body needs an SDK adapter')
        }
        for (const [name, property] of Object.entries(schema.properties)) {
            if (keep(name) && !resolveRef(spec, property).readOnly && !Object.hasOwn(config.inject_body ?? {}, name)) {
                add(name, property, (schema.required ?? []).includes(name), 'body')
            }
        }
    }
    if (config.response?.selectable) {
        if (!config.response.include?.length) {
            throw new Error('Selectable responses require an include allowlist')
        }
        input.properties.fields = {
            type: 'array',
            items: { type: 'string', enum: config.response.include },
            minItems: 1,
            description: 'Optional subset of the response field allowlist. Omit to return all allowed fields.',
        }
    }
    registry.add(`${prefix}Input`, input, 'input', { patch: resolved.method === 'PATCH' })
    const responses = {}
    for (const [status, rawResponse] of Object.entries(operation.responses ?? {})) {
        if (!/^2\d\d$/.test(status)) {
            continue
        }
        const response = resolveRef(spec, rawResponse)
        let schema = response.content?.['application/json']?.schema
        if (!schema) {
            if (status !== '204' && response.content && Object.keys(response.content).length) {
                throw new Error(`Unsupported response content for ${status}`)
            }
            schema = { type: 'null' }
        }
        schema = objectSchema(spec, schema)
        if (!schema.type && !schema.properties && !schema.oneOf && !schema.anyOf) {
            throw new Error(`Untyped response for ${status}`)
        }
        const shape = (value) =>
            projectSchema(
                spec,
                value,
                config.response?.include ?? config.response?.exclude,
                config.response?.include ? 'include' : 'exclude',
                config.response?.selectable
            )
        const urlField = {
            type: 'string',
            format: 'uri',
            description: 'URL of this resource in the public PostHog UI.',
        }
        const enrich = (value) => {
            if (value.type !== 'object' && !value.properties) {
                throw new Error('URL enrichment requires a structured object')
            }
            return {
                ...value,
                properties: { ...value.properties, _posthogUrl: urlField },
                required: [...new Set([...(value.required ?? []), '_posthogUrl'])],
            }
        }
        if (config.list) {
            if (!schema.properties?.results) {
                throw new Error('MCP list operations require a paginated results property')
            }
            const results = objectSchema(spec, schema.properties.results)
            let item = shape(results.items)
            if (config.enrich_url) {
                item = enrich(item)
            }
            schema = enrich({ ...schema, properties: { ...schema.properties, results: { ...results, items: item } } })
        } else {
            schema = shape(schema)
            if (config.enrich_url) {
                schema = enrich(schema)
            }
        }
        if (config.agent_note) {
            if (!schema.properties) {
                throw new Error('Agent notes require an object response')
            }
            schema = {
                ...schema,
                properties: {
                    ...schema.properties,
                    _agentNote: { type: 'string', description: 'Guidance carried over from the MCP tool definition.' },
                },
                required: [...(schema.required ?? []), '_agentNote'],
            }
        }
        const dataName = `${prefix}Data${Object.keys(operation.responses ?? {}).filter((s) => /^2\d\d$/.test(s)).length > 1 ? status : ''}`
        const data = registry.add(dataName, schema, 'output', { stripNulls: config.response?.strip_nulls })
        const outputName = `${prefix}Output${dataName.endsWith(status) ? status : ''}`
        registry.schemas[outputName] = {
            type: 'object',
            properties: { data, meta: { $ref: '#/components/schemas/ResponseMeta' } },
            required: ['data', 'meta'],
        }
        responses[status] = { outputName }
    }
    if (!Object.keys(responses).length) {
        throw new Error('No documented success response')
    }
    const outputs = Object.values(responses).map((response) => response.outputName)
    if (outputs.length > 1) {
        registry.schemas[`${prefix}Output`] = {
            type: 'object',
            properties: {
                data: { anyOf: outputs.map((name) => registry.schemas[name].properties.data) },
                meta: { $ref: '#/components/schemas/ResponseMeta' },
            },
            required: ['data', 'meta'],
        }
    }
    const documentation = resolveDocumentation(config, operation, yamlFile, repoRoot)
    return {
        namespace,
        method,
        prefix,
        registry,
        documentation,
        title: config.title ?? operation.summary ?? toolName,
        toolName,
        operationId: operation.operationId,
        category: config.category ?? category.category,
        requiredScopes: config.scopes ?? [
            ...new Set((operation.security ?? []).flatMap((entry) => Object.values(entry).flat())),
        ],
        annotations: config.annotations ?? {
            readOnly: resolved.method === 'GET',
            destructive: resolved.method === 'DELETE',
            idempotent: ['GET', 'DELETE'].includes(resolved.method),
        },
        selectionHint: config.system_prompt_hint,
        definition: {
            method: config.soft_delete ? 'PATCH' : resolved.method,
            path: resolved.path,
            bindings,
            injectBody: config.soft_delete ? { deleted: true } : (config.inject_body ?? {}),
            inputSchema: registry.runtime(`${prefix}Input`),
            responses: Object.fromEntries(
                Object.entries(responses).map(([status, value]) => [status, registry.runtime(value.outputName)])
            ),
            response: config.response ?? {},
            list: !!config.list,
            urlPrefix: config.url_prefix ?? category.url_prefix ?? '',
            ...(config.enrich_url ? { enrichUrl: config.enrich_url } : {}),
            ...(config.agent_note ? { agentNote: config.agent_note } : {}),
        },
    }
}
