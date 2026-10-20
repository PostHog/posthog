import path from 'node:path'

import { findOperation, resolveDocumentation } from './agent-operations.mjs'
import {
    annotateDocumentation,
    objectSchema,
    pascalCase,
    projectSchema,
    resolveRef,
    SchemaRegistry,
} from './sdk-schema.mjs'

export function camelCase(value) {
    const name = value.replace(/(^|[-_.\s]+)([a-z0-9])/gi, (_match, _separator, letter) => letter.toUpperCase())
    return name.charAt(0).toLowerCase() + name.slice(1)
}

function projectShared(spec, node, paths, mode, selectable) {
    if (!paths?.length) {
        return node
    }
    const schema = objectSchema(spec, node)
    const union = schema.anyOf ? 'anyOf' : schema.oneOf ? 'oneOf' : undefined
    if (union) {
        return { ...schema, [union]: schema[union].map((part) => projectShared(spec, part, paths, mode, selectable)) }
    }
    if (schema.type === 'null') {
        return schema
    }
    if (schema.type === 'array') {
        return {
            ...schema,
            items: projectShared(
                spec,
                schema.items,
                paths.map((name) => name.replace(/^\*\./, '')),
                mode,
                selectable
            ),
        }
    }
    const properties = { ...schema.properties }
    // A projection supplies field names even when the upstream serializer declares an open JSON object.
    for (const name of paths) {
        const [head, ...tail] = name.split('.')
        if (mode === 'include' && !Object.hasOwn(properties, head)) {
            properties[head] = {}
        }
        if (tail.length && properties[head]) {
            const siblings = paths
                .filter((value) => value.startsWith(`${head}.`))
                .map((value) => value.slice(head.length + 1))
            properties[head] = projectShared(spec, properties[head], siblings, mode, selectable)
        }
    }
    return projectSchema(
        spec,
        { ...schema, type: 'object', properties },
        paths.map((name) => name.split('.')[0]),
        mode,
        selectable
    )
}

function originalFieldComments(api, source, input) {
    if (!source?.config.operation) {
        return
    }
    const resolved = findOperation(api, source.config.operation)
    if (!resolved) {
        return
    }
    const operation = resolved.operation
    const body = operation.requestBody && resolveRef(api, operation.requestBody)
    const properties = body?.content?.['application/json']?.schema
        ? (objectSchema(api, body.content['application/json'].schema).properties ?? {})
        : {}
    const originals = { ...properties }
    for (const raw of operation.parameters ?? []) {
        const parameter = resolveRef(api, raw)
        originals[parameter.name] = {
            ...parameter.schema,
            ...(parameter.description ? { description: parameter.description } : {}),
        }
    }
    for (const [wireName, raw] of Object.entries(originals)) {
        const name = source.config.rename_params?.[wireName] ?? wireName
        const field = input.properties?.[name]
        const original = resolveRef(api, raw)
        if (!field || !original.description) {
            continue
        }
        if (field.description && field.description !== original.description) {
            field['x-source-description'] = original.description
            field['x-override-source'] = {
                kind: 'mcp_yaml',
                file: source.file,
                pointer: `/tools/${source.name}/param_overrides/${wireName}`,
            }
        } else {
            field.description = original.description
        }
        field['x-documentation-source'] = { kind: 'openapi', file: 'openapi.json', pointer: `/paths/${resolved.path}` }
    }
}

export function resolveSharedOperation({ api, inputSchema, resultType, source, metadata, toolName, names, repoRoot }) {
    const { namespace, method } = names
    const prefix = `${pascalCase(namespace)}${pascalCase(method)}`
    const input = structuredClone(inputSchema)
    const result = resultType ?? { schema: {}, definitions: {}, file: 'services/mcp/src/tools/index.ts' }
    const spec = { ...input, definitions: result.definitions, components: api.components }
    const registry = new SchemaRegistry(spec, prefix)
    annotateDocumentation(input, { kind: 'mcp_typescript', file: result.file })
    originalFieldComments(api, source, input)
    annotateDocumentation(result.schema, { kind: 'mcp_typescript', file: result.file })
    annotateDocumentation(spec.definitions, { kind: 'mcp_typescript', file: result.file })
    registry.add(`${prefix}Input`, input, 'input')
    let data = result.schema
    const config = source?.config
    if (config?.response && !toolName.endsWith('-prepare')) {
        const response = objectSchema(spec, data)
        const project = (value) =>
            projectShared(
                spec,
                value,
                config.response.include ?? config.response.exclude,
                config.response.include ? 'include' : 'exclude',
                config.response.selectable
            )
        if (config.list && response.properties?.results) {
            const items = objectSchema(spec, response.properties.results)
            data = {
                ...response,
                properties: { ...response.properties, results: { ...items, items: project(items.items) } },
            }
        } else if (response.properties) {
            data = project(data)
        }
    }
    if (config && !toolName.endsWith('-prepare')) {
        const response = objectSchema(spec, data)
        if (response.properties && (config.enrich_url || config.list || config.agent_note)) {
            data = { ...response, properties: { ...response.properties }, required: [...(response.required ?? [])] }
            if (config.enrich_url || config.list) {
                data.properties._posthogUrl = {
                    type: 'string',
                    description: 'Canonical PostHog URL returned by the MCP handler.',
                }
                data.required.push('_posthogUrl')
            }
            if (config.agent_note) {
                data.properties._agentNote = { type: 'string', description: config.agent_note }
                data.required.push('_agentNote')
            }
        }
    }
    if (toolName === 'session-recording-get') {
        data = {
            anyOf: [
                data,
                {
                    type: 'object',
                    properties: {
                        found: { const: false },
                        id: { type: 'string' },
                        reason: { const: 'recording_not_found' },
                        message: { type: 'string' },
                    },
                    required: ['found', 'id', 'reason', 'message'],
                },
            ],
        }
    }
    if (toolName === 'view-get') {
        const response = objectSchema(spec, data)
        const suggestion = api.components.schemas.WarehouseSuggestion
        data = {
            ...response,
            properties: {
                ...response.properties,
                open_suggestions: {
                    type: 'array',
                    items: {
                        type: 'object',
                        properties: Object.fromEntries(
                            ['id', 'kind', 'payload', 'can_act'].map((name) => [name, suggestion.properties[name]])
                        ),
                    },
                },
                open_suggestions_note: { type: 'string' },
            },
        }
    }
    const value = registry.add(`${prefix}Data`, data, 'output', { stripNulls: config?.response?.strip_nulls })
    registry.schemas[`${prefix}Output`] = {
        type: 'object',
        properties: { data: value, meta: { $ref: '#/components/schemas/ResponseMeta' } },
        required: ['data', 'meta'],
    }
    const resolved = config?.operation ? findOperation(api, config.operation) : undefined
    const documentation = source
        ? resolveDocumentation(config, resolved?.operation ?? {}, path.join(repoRoot, source.file), repoRoot)
        : { description: metadata.description, layers: [] }
    if (documentation.description !== metadata.description || !documentation.layers.length) {
        documentation.layers.push({
            role: documentation.layers.length ? 'override' : 'original',
            text: metadata.description,
            source: {
                kind: 'mcp_json',
                file: 'services/mcp/schema/tool-definitions-all.json',
                pointer: `/${toolName}/description`,
            },
        })
    }
    documentation.description = metadata.description
    if (toolName === 'agent-feedback') {
        documentation.description =
            'Send agent feedback to the feedback callback configured on createPostHogClient. The callback determines where feedback is delivered; this does not automatically submit it to the PostHog team. A missing callback is a configuration error, and callback failures are surfaced to the caller.'
        documentation.layers.push({
            role: 'override',
            text: documentation.description,
            source: { kind: 'adapter', file: 'services/mcp/sdk/host.ts' },
        })
    }
    return {
        namespace,
        method,
        prefix,
        registry,
        documentation,
        toolName,
        title: metadata.title ?? metadata.summary ?? toolName,
        category: metadata.category,
        operationId: resolved?.operation.operationId,
        requiredScopes: metadata.required_scopes ?? [],
        annotations: {
            readOnly: metadata.annotations.readOnlyHint,
            destructive: metadata.annotations.destructiveHint,
            idempotent: metadata.annotations.idempotentHint,
        },
        availability: ['feature_flag', 'feature_entitlement', 'requires_ai_consent', 'hidden_when_flag_on']
            .filter((key) => metadata[key])
            .map((key) => `${key}: ${metadata[key]}`),
        yamlFile: source?.file,
        definition: { sharedTool: toolName },
    }
}
