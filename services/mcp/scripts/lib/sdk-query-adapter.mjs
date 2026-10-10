import path from 'node:path'

import { findOperation, resolveDocumentation } from './agent-operations.mjs'
import { SchemaRegistry, pascalCase, resolveRef, unsupportedReason } from './sdk-schema.mjs'

const supported = new Set([
    'TrendsQuery',
    'FunnelsQuery',
    'RetentionQuery',
    'StickinessQuery',
    'LifecycleQuery',
    'PathsQuery',
    'HogQLQuery',
])
const adapterSource = { kind: 'adapter', file: 'services/mcp/scripts/lib/sdk-query-adapter.mjs' }

export function resolveQueryOperation(api, querySchema, config, category, toolName, yamlFile, repoRoot) {
    const endpoint = findOperation(api, 'query_create')
    if (!endpoint) {
        throw new Error('OpenAPI query_create operation is missing')
    }
    const reason = unsupportedReason(config, category, endpoint)
    if (reason) {
        throw new Error(reason)
    }
    const source = querySchema.definitions[config.schema_ref]
    const kind = source?.properties?.kind?.const
    if (!supported.has(kind)) {
        throw new Error(`${kind ?? config.schema_ref} needs a typed query adapter`)
    }
    const response = querySchema.definitions[kind]?.properties?.response
    if (!response) {
        throw new Error(`${kind} does not declare its response schema`)
    }
    const { namespace, method } = config.sdk
    const prefix = `${pascalCase(namespace)}${pascalCase(method)}`
    const registry = new SchemaRegistry(querySchema, prefix)
    const excluded = new Set(['kind', 'response', ...(config.exclude_properties ?? [])])
    const properties = Object.fromEntries(
        Object.entries(source.properties)
            .filter(([name]) => !excluded.has(name))
            .map(([name, value]) => [name, structuredClone(value)])
    )
    const filterTestAccounts = Object.hasOwn(properties, 'filterTestAccounts')
    if (filterTestAccounts) {
        const property = properties.filterTestAccounts
        delete property.default
        property['x-source-description'] = property.description
        property['x-override-source'] = adapterSource
        property.description =
            'Exclude internal and test users. When omitted, read the project default. Supply an explicit value if the credential cannot read project settings.'
    }
    const query = {
        ...source,
        properties: { ...properties, kind: source.properties.kind },
        required: (source.required ?? []).filter((name) => name === 'kind' || Object.hasOwn(properties, name)),
    }
    const refresh = structuredClone(querySchema.definitions.QueryRequest.properties.refresh)
    delete refresh.default
    const input = {
        ...source,
        properties: { ...properties, refresh },
        required: (source.required ?? []).filter((name) => Object.hasOwn(properties, name)),
    }
    registry.add(`${prefix}Input`, input, 'input')
    const queryRef = registry.add(`${prefix}Query`, query, 'output')
    const resultSchema = { ...resolveRef(querySchema, response), additionalProperties: true }
    if (['TrendsQuery', 'FunnelsQuery', 'HogQLQuery'].includes(kind)) {
        resultSchema.properties = {
            ...resultSchema.properties,
            results: {
                ...resultSchema.properties.results,
                description:
                    kind === 'HogQLQuery'
                        ? 'Rows returned by this SQL query. Column names and cell types depend on the query; inspect columns and types and decode values before using a narrower row type.'
                        : 'Query results. The source query schema does not specify the series fields; inspect the JSON values before interpreting this result.',
                'x-override-source': adapterSource,
            },
        }
    }
    // schema.py makes optional query fields nullable, and the query API serializes models without exclude_none.
    const result = registry.add(`${prefix}Result`, resultSchema, 'output', { nullOptional: true })
    const queryStatus = registry.add(`${prefix}QueryStatus`, { $ref: '#/definitions/QueryStatus' }, 'output', {
        nullOptional: true,
    })
    const common = {
        query: queryRef,
        _posthogUrl: { type: 'string', format: 'uri', description: 'URL to open this query in the public PostHog UI.' },
    }
    const variants = [
        ['CompletedData', 'complete', { result }, ['result']],
        ['PendingData', 'pending', { queryStatus }, ['queryStatus']],
        [
            'FailedData',
            'failed',
            { queryStatus, error: { type: 'string', description: 'Failure reported by query execution.' } },
            ['error'],
        ],
    ].map(([suffix, state, fields, required]) => {
        const name = `${prefix}${suffix}`
        registry.schemas[name] = {
            type: 'object',
            properties: { state: { type: 'string', const: state }, ...common, ...fields },
            required: ['state', 'query', '_posthogUrl', ...required],
        }
        return { $ref: `#/components/schemas/${name}` }
    })
    registry.schemas[`${prefix}Output`] = {
        type: 'object',
        properties: { data: { oneOf: variants }, meta: { $ref: '#/components/schemas/ResponseMeta' } },
        required: ['data', 'meta'],
    }
    const documentation = resolveDocumentation(config, endpoint.operation, yamlFile, repoRoot)
    return {
        namespace,
        method,
        prefix,
        registry,
        documentation,
        toolName,
        title: config.title ?? toolName,
        category: category.category ?? 'Queries',
        operationId: endpoint.operation.operationId,
        requiredScopes: config.scopes ?? ['query:read'],
        annotations: config.annotations ?? { readOnly: true, destructive: false, idempotent: true },
        selectionHint: config.system_prompt_hint,
        availability: filterTestAccounts
            ? [
                  'Omitting filterTestAccounts requires access to project settings. Supply an explicit boolean to avoid that lookup.',
              ]
            : [],
        definition: {
            method: 'POST',
            path: endpoint.path,
            bindings: Object.keys(input.properties).map((name) => ({ name, wireName: name, location: 'body' })),
            injectBody: {},
            inputSchema: registry.runtime(`${prefix}Input`),
            responses: { 200: registry.runtime(`${prefix}Output`), 202: registry.runtime(`${prefix}Output`) },
            query: { kind, filterTestAccounts },
            response: {},
            list: false,
            urlPrefix: '/insights/new',
        },
    }
}

export function resolveSqlOperation(api, querySchema, metadata, repoRoot) {
    const description = metadata.description.replace(
        /IMPORTANT: By default, large JSON values[^\n]*/,
        'Results are returned as structured JSON without MCP text truncation. Inspect the columns and types metadata before decoding rows.'
    )
    const config = {
        schema_ref: 'HogQLQuery',
        sdk: { namespace: 'queries', method: 'sql' },
        title: metadata.title,
        description,
        scopes: metadata.required_scopes,
    }
    const operation = resolveQueryOperation(
        api,
        querySchema,
        config,
        { category: metadata.category },
        'execute-sql',
        path.join(repoRoot, 'services/mcp/schema/tool-definitions.json'),
        repoRoot
    )
    operation.documentation.layers = [
        {
            role: 'original',
            text: metadata.description,
            source: {
                kind: 'mcp_json',
                file: 'services/mcp/schema/tool-definitions.json',
                pointer: '/execute-sql/description',
            },
        },
        { role: 'override', text: description, source: adapterSource },
    ]
    operation.yamlFile = 'services/mcp/schema/tool-definitions.json'
    return operation
}
