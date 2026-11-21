import { findOperation } from './agent-operations.mjs'
import { objectSchema, resolveRef } from './sdk-schema.mjs'

const manualOperations = {
    'external-data-sources-db-schema': 'external_data_sources_database_schema_create',
    'external-data-sources-jobs': 'external_data_sources_jobs_list',
    'external-data-sources-preview-resource': 'external_data_sources_preview_resource_create',
    'external-data-sync-logs': 'external_data_schemas_logs_retrieve',
    'workflows-run-batch': 'hog_flows_batch_jobs_create',
    'workflows-schedule-create': 'hog_flows_schedules_create',
}

export function sharedResultType(toolName, source, api, querySchema, readResult) {
    const result = readResult(toolName)
    if (toolName.startsWith('llma-skill-')) {
        const target = sharedResultType(
            toolName.replace('llma-skill-', 'skill-'),
            undefined,
            api,
            querySchema,
            readResult
        )
        const schema = objectSchema({ definitions: target.definitions, components: api.components }, target.schema)
        return {
            ...target,
            schema: {
                ...schema,
                type: 'object',
                properties: {
                    ...schema.properties,
                    _deprecation_notice: {
                        type: 'string',
                        description: 'The current tool name to use instead of this deprecated alias.',
                    },
                },
                required: [...(schema.required ?? []), '_deprecation_notice'],
            },
        }
    }
    if (source?.config.schema_ref) {
        const definition = querySchema.definitions[source.config.schema_ref]
        const kind = definition?.properties?.kind?.const
        if (!kind) {
            throw new Error(`${toolName} has no query kind`)
        }
        const response = querySchema.definitions[kind]?.properties?.response
        const responseSchema = response ? resolveRef(querySchema, response) : undefined
        const query = structuredClone(definition)
        delete query.properties.response
        const properties = {
            _posthogUrl: { type: 'string', description: 'Canonical PostHog URL returned by the query tool.' },
            query,
            results: responseSchema?.properties?.results ?? {
                description:
                    'The query schema does not specify a result shape. Inspect these JSON values before using them.',
            },
            warnings: {
                type: 'array',
                items: {
                    type: 'object',
                    properties: { type: { type: 'string' }, message: { type: 'string' } },
                    additionalProperties: {},
                },
            },
            __formatted_results_override: {
                type: 'string',
                description: 'Formatted results supplied by the query tool.',
            },
        }
        let required = ['_posthogUrl', 'query', 'results']
        if (kind.endsWith('ActorsQuery')) {
            properties.query = {
                type: 'object',
                properties: {
                    kind: { const: 'ActorsQuery' },
                    source: query,
                    select: { type: 'array', items: { type: 'string' } },
                    limit: { type: 'number' },
                    offset: { type: 'number' },
                    orderBy: { type: 'array', items: { type: 'string' } },
                },
                required: ['kind', 'source', 'select', 'limit', 'offset'],
            }
            properties.results = {
                type: 'object',
                properties: {
                    columns: { type: 'array', items: { type: 'string' } },
                    results: { type: 'array', items: { type: 'array', items: {} } },
                },
                required: ['columns', 'results'],
            }
            Object.assign(properties, {
                hasMore: { type: 'boolean' },
                limit: { type: 'number' },
                offset: { type: 'number' },
            })
            required.push('hasMore', 'limit', 'offset')
        }
        if (kind === 'TraceQuery' || kind === 'TracesQuery') {
            properties.results = {
                type: 'array',
                items: {
                    type: 'object',
                    additionalProperties: {},
                    description:
                        'Redacted trace fields. Large values can be shortened; omitted events and traces carry _truncated metadata.',
                },
            }
            required = ['results']
        }
        return {
            schema: { type: 'object', properties, required },
            definitions: querySchema.definitions,
            file: 'services/mcp/src/tools/query-wrapper-factory.ts',
        }
    }
    if (result?.schema.$ref || result?.schema.type || result?.schema.anyOf) {
        return result
    }
    const operationId = source?.config.operation ?? manualOperations[toolName]
    const resolved = operationId && findOperation(api, operationId)
    if (resolved && !toolName.endsWith('-prepare')) {
        const successes = Object.entries(resolved.operation.responses ?? {}).filter(([status]) =>
            /^2\d\d$/.test(status)
        )
        const bodies = successes.map(([status, raw]) => {
            const response = resolveRef(api, raw)
            return (
                response.content?.['application/json']?.schema ??
                (response.content?.['text/plain']
                    ? { type: 'string' }
                    : status === '204'
                      ? { type: 'object', properties: {}, additionalProperties: false }
                      : undefined)
            )
        })
        if (bodies.length && bodies.every(Boolean)) {
            return {
                schema: bodies.length === 1 ? bodies[0] : { anyOf: bodies },
                definitions: {},
                file: 'services/mcp/src/api/generated.ts',
            }
        }
    }
    if (toolName === 'posthog-connection-call') {
        return {
            schema: {
                type: 'object',
                properties: {
                    ran_in: {
                        type: 'object',
                        properties: {
                            project_id: { type: 'number' },
                            project_name: { type: 'string' },
                            organization_name: { type: 'string' },
                            region: { type: 'string' },
                        },
                        required: ['project_id', 'project_name', 'organization_name', 'region'],
                    },
                    tool: { type: 'string' },
                    result: {
                        description:
                            'Result of the selected tool. Use its catalog entry to inspect the result interface.',
                    },
                },
                required: ['ran_in', 'tool', 'result'],
            },
            definitions: {},
            file: 'services/mcp/src/tools/posthogConnections/call.ts',
        }
    }
    return result ?? { schema: {}, definitions: {}, file: 'services/mcp/src/tools/index.ts' }
}
