/**
 * Executes API requests against the PostHog API.
 *
 * Resolves path params ({project_id}, {id}, etc.), separates query vs body
 * params, and makes the HTTP request. Also provides a dry-run mode that
 * previews the request without executing.
 *
 * Query wrapper tools (those with `query_kind`) POST to the query endpoint
 * with the payload wrapped in `{ query: { kind, ...params } }`.
 */

import type { CliConfig } from './config.js'
import type { CliToolManifest } from './manifest.js'

interface ResolvedRequest {
    method: string
    url: string
    headers: Record<string, string>
    body?: Record<string, unknown>
}

function makeHeaders(config: CliConfig): Record<string, string> {
    return {
        Authorization: `Bearer ${config.apiKey}`,
        'Content-Type': 'application/json',
        'X-PostHog-Client': 'cli-agent',
    }
}

function buildQueryWrapperRequest(
    tool: CliToolManifest,
    params: Record<string, unknown>,
    config: CliConfig
): ResolvedRequest {
    const resolvedPath = tool.path.replace('{project_id}', config.projectId)
    const url = `${config.host}${resolvedPath}`

    // Build the query payload: inject `kind`, handle filterGroup transform
    const query: Record<string, unknown> = { ...params, kind: tool.query_kind }

    // Convert flat filterGroup arrays into the nested PropertyGroupFilter
    // structure the query API expects (same transform as MCP's query-wrapper-factory).
    if (Array.isArray(query['filterGroup'])) {
        const filters = query['filterGroup'] as unknown[]
        if (filters.length > 0) {
            query['filterGroup'] = {
                type: 'AND',
                values: [{ type: 'AND', values: filters }],
            }
        } else {
            delete query['filterGroup']
        }
    }

    return { method: 'POST', url, headers: makeHeaders(config), body: { query } }
}

function buildRequest(tool: CliToolManifest, params: Record<string, unknown>, config: CliConfig): ResolvedRequest {
    if (tool.query_kind) {
        return buildQueryWrapperRequest(tool, params, config)
    }

    // Resolve path template — replace {project_id} with config, others from params
    let resolvedPath = tool.path.replace('{project_id}', config.projectId)

    for (const pathParam of tool.params.path) {
        const value = params[pathParam]
        if (value === undefined) {
            throw new Error(`Missing required path parameter: ${pathParam}`)
        }
        resolvedPath = resolvedPath.replace(`{${pathParam}}`, String(value))
    }

    // Also handle {organization_id} if present
    if (resolvedPath.includes('{organization_id}')) {
        const orgId = params['organization_id']
        if (orgId === undefined) {
            throw new Error('Missing required parameter: organization_id (this tool requires an org ID)')
        }
        resolvedPath = resolvedPath.replace('{organization_id}', String(orgId))
    }

    // Build query string from query params
    const queryParts: string[] = []
    for (const qp of tool.params.query) {
        const value = params[qp]
        if (value !== undefined) {
            queryParts.push(`${encodeURIComponent(qp)}=${encodeURIComponent(String(value))}`)
        }
    }
    const qs = queryParts.length > 0 ? `?${queryParts.join('&')}` : ''

    // Build body from body params (or soft-delete override)
    let body: Record<string, unknown> | undefined
    if (tool.soft_delete) {
        const field = typeof tool.soft_delete === 'string' ? tool.soft_delete : 'deleted'
        body = { [field]: true }
    } else if (tool.params.body.length > 0) {
        body = {}
        for (const bp of tool.params.body) {
            if (params[bp] !== undefined) {
                body[bp] = params[bp]
            }
        }
        // Also include any unknown params in the body for flexibility
        // (the API will reject unknown fields if needed)
        for (const [key, value] of Object.entries(params)) {
            if (!tool.params.path.includes(key) && !tool.params.query.includes(key) && !(key in body)) {
                body[key] = value
            }
        }
    }

    const url = `${config.host}${resolvedPath}${qs}`
    return { method: tool.method, url, headers: makeHeaders(config), body }
}

export function dryRun(
    tool: CliToolManifest,
    params: Record<string, unknown>,
    config: CliConfig
): { method: string; url: string; body?: Record<string, unknown>; tool: string; title: string } {
    const req = buildRequest(tool, params, config)
    return {
        tool: tool.title,
        title: tool.title,
        method: req.method,
        url: req.url,
        ...(req.body ? { body: req.body } : {}),
    }
}

export async function execute(
    tool: CliToolManifest,
    params: Record<string, unknown>,
    config: CliConfig
): Promise<unknown> {
    const req = buildRequest(tool, params, config)

    const response = await fetch(req.url, {
        method: req.method,
        headers: req.headers,
        ...(req.body ? { body: JSON.stringify(req.body) } : {}),
    })

    if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`${req.method} ${req.url} → ${response.status} ${response.statusText}\n${errorText}`)
    }

    // Some endpoints return 204 No Content
    if (response.status === 204) {
        return { status: 'ok' }
    }

    return response.json()
}
