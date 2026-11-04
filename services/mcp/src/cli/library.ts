// The tool catalog and tool calls, for CLIs that embed them in-process. `scripts/build-cli-library.ts`
// bundles this file. Calls run through the exec tool, so validation, destructive confirmation,
// output formatting and analytics match `posthog-cli api call`.
import { hasScope } from '@/lib/api'
import {
    ExecCommandError,
    MCPToolResultError,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogTransportError,
    PostHogValidationError,
    ToolInputValidationError,
} from '@/lib/errors'
import { createExecTool, formatInputValidationError, repairArgumentNesting } from '@/tools/exec'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { buildCliContext, flushAnalytics } from './context'
import type {
    ApiConnection,
    ApiKeyAccess,
    ApiSearchResult,
    ApiToolError,
    ApiToolLibrary,
    ApiToolResult,
    ApiToolSummary,
    ApiToolValidation,
} from './library-types'
import { trackCliToolCall } from './tool-call-properties'
import { getCliTools } from './tools'

const COMMAND_REFERENCE = 'CLI-style command string: search, schema or call.'

function staticExec(tools: Tool<ZodObjectAny>[]): Tool<ZodObjectAny> {
    return createExecTool(tools, undefined, 'PostHog tools', COMMAND_REFERENCE, undefined, undefined, [], {
        requireDestructiveConfirmation: true,
    })
}

async function runExec(exec: Tool<ZodObjectAny>, context: Context | undefined, command: string): Promise<unknown> {
    const output = await exec.handler(context as Context, { command })
    return typeof output === 'string' ? JSON.parse(output) : output
}

function summarize(tool: Tool<ZodObjectAny>): ApiToolSummary {
    const definition = getToolDefinition(tool.name)
    return {
        name: tool.name,
        title: tool.title,
        summary: definition.summary,
        description: tool.description,
        group: definition.category,
        feature: definition.feature,
        requiredScopes: tool.scopes,
        readOnly: tool.annotations.readOnlyHint,
        destructive: tool.annotations.destructiveHint,
        idempotent: tool.annotations.idempotentHint,
        openWorld: tool.annotations.openWorldHint,
        requiresAiConsent: definition.requires_ai_consent === true,
    }
}

// The API answers errors as DRF JSON, so its `detail` reads better than the raw body.
function apiErrorDetail(error: PostHogApiError): string {
    try {
        const body = JSON.parse(error.body) as { detail?: unknown }
        return typeof body.detail === 'string' ? body.detail : error.message
    } catch {
        return error.message
    }
}

const MCP_RESULT_CODES: Record<MCPToolResultError['errorType'], ApiToolError['code']> = {
    validation: 'validation_error',
    permission: 'permission_denied',
    rate_limited: 'rate_limited',
    api_5xx: 'api_error',
    timeout: 'tool_error',
    memory_limit: 'tool_error',
    internal: 'tool_error',
}

function typedError(error: unknown): ApiToolError | undefined {
    if (error instanceof MCPToolResultError) {
        return { code: MCP_RESULT_CODES[error.errorType], message: error.message }
    }
    if (error instanceof PostHogPermissionError) {
        return {
            code: 'permission_denied',
            message: error.message,
            status: 403,
            ...(error.missingScope ? { missingScope: error.missingScope } : {}),
        }
    }
    if (error instanceof PostHogValidationError) {
        return { code: 'validation_error', message: error.message, status: 400 }
    }
    if (error instanceof PostHogRateLimitError) {
        return { code: 'rate_limited', message: error.message, status: 429 }
    }
    if (error instanceof PostHogApiError) {
        return { code: 'api_error', message: apiErrorDetail(error), status: error.status }
    }
    if (error instanceof PostHogTransportError) {
        return { code: 'unreachable', message: error.message }
    }
    if (error instanceof ToolInputValidationError) {
        return { code: 'invalid_input', message: error.message }
    }
    if (error instanceof ExecCommandError) {
        const codes: Partial<Record<ExecCommandError['reason'], ApiToolError['code']>> = {
            needs_confirmation: 'needs_confirmation',
            missing_scope: 'permission_denied',
            tool_not_granted: 'permission_denied',
        }
        return { code: codes[error.reason] ?? 'invalid_input', message: error.message }
    }
    return undefined
}

// Some tool handlers wrap the API failure, so the typed error can sit anywhere in the `cause` chain.
export function toApiToolError(error: unknown): ApiToolError {
    const seen = new Set<unknown>()
    for (
        let current = error;
        current instanceof Error && !seen.has(current);
        current = (current as Error & { cause?: unknown }).cause
    ) {
        seen.add(current)
        const typed = typedError(current)
        if (typed) {
            return typed
        }
    }
    return { code: 'tool_error', message: error instanceof Error ? error.message : String(error) }
}

class Failure extends Error {
    constructor(readonly failure: ApiToolError) {
        super(failure.message)
    }
}

function failure(error: ApiToolError): never {
    throw new Failure(error)
}

async function attempt<T>(work: () => Promise<T>): Promise<ApiToolResult<T>> {
    try {
        return { ok: true, value: await work() }
    } catch (error) {
        return { ok: false, error: error instanceof Failure ? error.failure : toApiToolError(error) }
    }
}

function buildContext(connection: ApiConnection): Promise<Context> {
    return buildCliContext(
        {
            apiKey: connection.apiKey,
            host: connection.host,
            version: 2,
            ...(connection.projectId ? { projectId: connection.projectId } : {}),
            ...(connection.organizationId ? { organizationId: connection.organizationId } : {}),
        },
        {
            clientName: connection.clientName,
            userAgent: `${connection.clientName}/${connection.clientVersion}`,
            source: `${connection.clientName}_cli`,
        }
    )
}

export function createApiToolLibrary(): ApiToolLibrary {
    // The catalog lists every tool. A call only offers the AI consent tools when the organization allows them.
    const tools = getCliTools({ aiConsentGiven: true })
    const byName = new Map(tools.map((tool) => [tool.name, tool]))
    const exec = staticExec(tools)
    const find = (name: string): Tool<ZodObjectAny> => {
        const tool = byName.get(name)
        if (!tool) {
            throw new Error(`Unknown tool: "${name}".`)
        }
        return tool
    }
    // Each context registers a cache that lives as long as the process.
    const contexts = new Map<string, Promise<Context>>()
    const contextFor = (connection: ApiConnection): Promise<Context> => {
        const key = JSON.stringify(connection)
        let context = contexts.get(key)
        if (!context) {
            context = buildContext(connection)
            contexts.set(key, context)
        }
        return context
    }

    return {
        tools: () => tools.map(summarize),

        async search(query: string): Promise<ApiSearchResult> {
            const result = await runExec(exec, undefined, `search ${query}`)
            if (Array.isArray(result)) {
                return { names: result as string[], truncated: false }
            }
            const object = (result ?? {}) as { matches?: string[]; truncated?: boolean }
            return { names: object.matches ?? [], truncated: object.truncated === true }
        },

        async schema(tool: string, fieldPath?: string): Promise<unknown> {
            find(tool)
            return runExec(exec, undefined, `schema ${tool}${fieldPath ? ` ${fieldPath}` : ''}`)
        },

        // The same rewrap and messages as `posthog-cli api call --dry-run`.
        validate(name: string, input: Record<string, unknown>): ApiToolValidation {
            const { schema } = find(name)
            const first = schema.safeParse(input, { reportInput: true })
            const rewrapped = first.success ? undefined : repairArgumentNesting(first.error, input, schema)
            const result = rewrapped ? schema.safeParse(rewrapped, { reportInput: true }) : first
            return result.success
                ? { valid: true, input: result.data as Record<string, unknown> }
                : { valid: false, error: formatInputValidationError(name, result.error, input, schema) }
        },

        missingScopes: (granted, required) => required.filter((scope) => !hasScope(granted, scope)),

        keyAccess: (
            connection: ApiConnection,
            options: { signal?: AbortSignal } = {}
        ): Promise<ApiToolResult<ApiKeyAccess>> =>
            attempt(async () => {
                const context = await contextFor(connection)
                const result = await context.api.apiKeys().current(options)
                if (!result.success) {
                    throw result.error
                }
                return {
                    scopes: result.data.scopes ?? [],
                    scopedTeams: result.data.scoped_teams ?? [],
                    scopedOrganizations: result.data.scoped_organizations ?? [],
                }
            }),

        call: (name, input, connection, confirm): Promise<ApiToolResult<unknown>> =>
            attempt(async () => {
                find(name)
                const context = await contextFor(connection)
                const aiConsentGiven = await context.stateManager.getAiConsentGiven()
                if (getToolDefinition(name).requires_ai_consent && !aiConsentGiven) {
                    failure({
                        code: 'ai_consent_required',
                        message: `${name} sends data to an AI provider, and the organization has not allowed that.`,
                    })
                }
                const callExec = createExecTool(
                    getCliTools({ aiConsentGiven }),
                    context,
                    'PostHog tools',
                    COMMAND_REFERENCE,
                    connection.clientName,
                    (toolName, properties) => trackCliToolCall(context, toolName, properties),
                    [],
                    { requireDestructiveConfirmation: true }
                )
                return runExec(
                    callExec,
                    context,
                    `call --json ${confirm ? '--confirm ' : ''}${name} ${JSON.stringify(input)}`
                )
            }),

        flush: () => flushAnalytics(),
    }
}
