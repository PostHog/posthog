import type { ListToolsResult } from '@modelcontextprotocol/sdk/types.js'

import {
    buildToolResultPayload,
    estimateResponseTokens,
    isToolCallPayload,
    type ToolResultPayload,
} from '@/lib/build-tool-result'
import {
    ExecCommandError,
    handleToolError,
    MissingOrganizationContextError,
    MissingProjectContextError,
    PostHogApiError,
    PostHogValidationError,
    ToolInputValidationError,
    findPostHogPermissionError,
    findRecoverableApiError,
} from '@/lib/errors'
import { estimateTokens } from '@/lib/estimate-tokens'
import { resolveGatewayTools } from '@/lib/gateway-tools'
import { getPostHogClient } from '@/lib/posthog'
import {
    createExecTool,
    describeApiValidationError,
    describeExecCommand,
    describeValidationError,
    formatInputValidationError,
    parseExecCallInnerArgs,
    parseExecCallInnerToolName,
    type ExecCommandMeta,
    type ExecInnerCallTracker,
} from '@/tools/exec'
import { EXECUTE_SQL_TOOL_NAME } from '@/tools/posthogAiTools/executeSql'
import { createRenderUiTool } from '@/tools/render-ui'
import { skillAnalyticsProperties } from '@/tools/skills/analytics'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import {
    trackExecuteSqlGeneration,
    trackToolCall,
    trackToolSpan,
    trackToolsList,
    type ToolCallIntentMeta,
} from './analytics'
import type { InstructionsBuilder } from './instructions'
import { getEffectiveMCPClientContext } from './mcp-context'
import { toolCallDurationSeconds, toolCallsTotal, toolErrorsTotal } from './metrics'
import type { ResolvedState } from './request-state-resolver'
import type { ToolCatalog } from './tool-catalog'

interface ResolvedTool {
    name: string
    schema: ZodObjectAny
    handler: (ctx: Context, args: unknown) => Promise<unknown>
    _meta?: { ui?: { resourceUri?: string }; [key: string]: unknown } | undefined
}

interface ExecMetricState {
    innerToolName: string | undefined
    /** What the agent asked for, merged onto the event whichever verb ran. */
    commandMeta: ExecCommandMeta | undefined
}

export class ToolExecutor {
    private readonly catalog: ToolCatalog
    private readonly instructionsBuilder: InstructionsBuilder

    constructor(catalog: ToolCatalog, instructionsBuilder: InstructionsBuilder) {
        this.catalog = catalog
        this.instructionsBuilder = instructionsBuilder
    }

    async handleToolsList(state: ResolvedState): Promise<ListToolsResult> {
        const tools = this.injectContext(this.buildAdvertisedTools(state))

        void trackToolsList(
            tools.map((t) => t.name),
            state
        )

        return { tools }
    }

    // Inject the `context` argument into every advertised tool so agents can state
    // what they're trying to do (`handleToolCall` strips it before validation and
    // surfaces it as `$mcp_intent` — the same injection `instrument()` does for
    // SDK-wrapped servers). Guarded: analytics must never break `tools/list`, so
    // any failure falls back to the un-augmented tools.
    private injectContext(tools: ListToolsResult['tools']): ListToolsResult['tools'] {
        try {
            return getPostHogClient().prepareToolList(tools)
        } catch {
            return tools
        }
    }

    private buildAdvertisedTools(state: ResolvedState): ListToolsResult['tools'] {
        if (state.useSingleExec) {
            const renderUiEntry = state.renderUiEnabled ? this.instructionsBuilder.buildRenderUiToolEntry(state) : null
            return [this.instructionsBuilder.buildExecToolEntry(state), ...(renderUiEntry ? [renderUiEntry] : [])]
        }

        const nameSet = new Set(state.allTools.map((t) => t.name))
        const filteredTools = this.catalog.getPreBuiltEntries().filter((e) => nameSet.has(e.name))

        return filteredTools.map((entry) => {
            if (entry.name === EXECUTE_SQL_TOOL_NAME) {
                return {
                    ...entry,
                    description: this.instructionsBuilder.formatExecuteSqlDescription(),
                }
            }
            return entry
        })
    }

    async handleToolCall(params: Record<string, unknown> | undefined, state: ResolvedState): Promise<unknown> {
        const toolName = params?.name as string
        if (!toolName) {
            return { content: [{ type: 'text', text: 'Missing tool name' }], isError: true }
        }

        const { intentMeta, args } = this.extractIntent(toolName, (params?.arguments ?? {}) as Record<string, unknown>)
        const callParams = { ...params, arguments: args }

        if (toolName === 'exec') {
            return this.callExecTool(callParams, state, intentMeta)
        }

        if (toolName === 'render-ui') {
            // render-ui is only advertised to MCP Apps hosts; reject calls from others.
            if (!state.renderUiEnabled) {
                toolCallsTotal.inc({ tool: toolName, status: 'error' })
                return { content: [{ type: 'text', text: `Tool ${toolName} not found` }], isError: true }
            }
            return this.callRenderUiTool(callParams, state, intentMeta)
        }

        if (!state.allTools.some((t) => t.name === toolName)) {
            toolCallsTotal.inc({ tool: toolName, status: 'error' })
            return { content: [{ type: 'text', text: `Tool ${toolName} not found` }], isError: true }
        }

        const preBuilt = this.catalog.getToolByName(toolName)
        if (!preBuilt) {
            toolCallsTotal.inc({ tool: toolName, status: 'error' })
            return { content: [{ type: 'text', text: `Tool ${toolName} not found` }], isError: true }
        }

        return this.callTool(
            {
                name: toolName,
                schema: preBuilt.base.schema,
                handler: (ctx, args) => preBuilt.base.handler(ctx, args),
                _meta: preBuilt.base._meta,
            },
            callParams,
            state,
            intentMeta
        )
    }

    // execute-sql is the one tool whose advertised description is formatted per
    // request (the schema-discovery splice is assembled at render time) instead of served
    // from the catalog, on both the native tools/list path and exec's `info` output.
    // trackToolCall stamps the catalog text by default, so it needs the served text
    // for this tool or $mcp_tool_description records words the agent never saw.
    private servedToolDescription(toolName: string): string | undefined {
        if (toolName === EXECUTE_SQL_TOOL_NAME) {
            return this.instructionsBuilder.formatExecuteSqlDescription()
        }
        return undefined
    }

    // Pull the agent's stated intent off the injected `context` arg and strip it so
    // tool schemas/handlers never see it (validation is `.strict()` in places). The
    // intent rides through to `$mcp_intent` on the captured event. Guarded: analytics
    // must never break `tools/call`, so on failure we fall back to the raw args —
    // safe because `context` is only present when the matching injection succeeded.
    private extractIntent(
        toolName: string,
        rawArgs: Record<string, unknown>
    ): { intentMeta: ToolCallIntentMeta; args: Record<string, unknown> } {
        try {
            const prepared = getPostHogClient().prepareToolCall(toolName, rawArgs)
            return {
                intentMeta: { intent: prepared.intent, intentSource: prepared.intentSource },
                args: prepared.args ?? rawArgs,
            }
        } catch {
            return { intentMeta: {}, args: rawArgs }
        }
    }

    private async callTool(
        tool: ResolvedTool,
        params: Record<string, unknown> | undefined,
        state: ResolvedState,
        intentMeta?: ToolCallIntentMeta
    ): Promise<unknown> {
        const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
        const validation = tool.schema.safeParse(toolArgs, { reportInput: true })
        if (!validation.success) {
            toolCallsTotal.inc({ tool: tool.name, status: 'validation_error' })
            const message = formatInputValidationError(tool.name, validation.error)
            // Emit the same errored `$mcp_tool_call` the exec path emits for an
            // identical rejection. Without it, direct-mode ('tools') schema
            // rejections are absent from analytics entirely — so every
            // exec-vs-direct comparison silently flatters direct mode, and
            // clients registered individually look error-free when they aren't.
            // Duration is 0: no handler ran (see `trackInnerCall`, same rule).
            const rejection = new ToolInputValidationError(
                message,
                describeValidationError(validation.error, toolArgs, tool.schema)
            )
            void trackToolCall(
                tool.name,
                0,
                true,
                state,
                errorAnalyticsProperties(classifyToolError(rejection, tool.name), rejection),
                intentMeta,
                this.servedToolDescription(tool.name)
            )
            return {
                content: [{ type: 'text', text: message }],
                isError: true,
            }
        }

        const stop = toolCallDurationSeconds.startTimer({ tool: tool.name })
        const startMs = Date.now()

        // Which stored skill a skill-* read returned. Empty for every other tool, and
        // stamped only on success: a read that failed delivered no skill, so counting
        // it would let a deleted skill agents keep requesting read as a popular one.
        // The exec path stamps the same properties from its command string.
        const skillShape = skillAnalyticsProperties(tool.name, validation.data)

        try {
            const isContextSwitch = tool.name === 'switch-project' || tool.name === 'switch-organization'
            const previousContext = isContextSwitch
                ? await state.reqCtx.safelyGetAnalyticsContext(state.context)
                : undefined

            const handlerResult = await tool.handler(state.context, validation.data)

            if (isContextSwitch) {
                void state.reqCtx.trackContextSwitchEvent(tool.name, state.context, previousContext)
            }

            toolCallsTotal.inc({ tool: tool.name, status: 'success' })
            stop({ status: 'success' })

            const duration = Date.now() - startMs

            let response: ToolResultPayload
            if (isToolCallPayload(handlerResult)) {
                response = handlerResult
            } else {
                const hasUiResource = !!tool._meta?.ui?.resourceUri
                const needsDistinctId = hasUiResource && typeof handlerResult !== 'string'
                const distinctId = needsDistinctId ? state.distinctId : undefined

                response = buildToolResultPayload({
                    handlerResult,
                    toolMeta: tool._meta,
                    toolName: tool.name,
                    params: validation.data,
                    suppressStructuredContentForFormattedResults: state.clientProfile.isCliModeEnabled(),
                    distinctId,
                })
            }

            void trackToolCall(
                tool.name,
                duration,
                false,
                state,
                {
                    ...skillShape,
                    input_tokens: estimateTokens(validation.data),
                    output_tokens: estimateResponseTokens(response),
                },
                intentMeta,
                this.servedToolDescription(tool.name)
            )

            if (tool.name === EXECUTE_SQL_TOOL_NAME) {
                void trackExecuteSqlGeneration(
                    tool.name,
                    validation.data,
                    state,
                    { durationMs: duration, isError: false },
                    intentMeta
                )
            }

            void trackToolSpan(tool.name, state, {
                durationMs: duration,
                isError: false,
                input: validation.data,
                output: response,
            })

            return response
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: tool.name, status: 'error' })
            stop({ status: 'error' })
            const classification = classifyToolError(error, tool.name)

            void trackToolCall(
                tool.name,
                Date.now() - startMs,
                true,
                state,
                errorAnalyticsProperties(classification, error),
                intentMeta,
                this.servedToolDescription(tool.name)
            )

            if (tool.name === EXECUTE_SQL_TOOL_NAME) {
                void trackExecuteSqlGeneration(
                    tool.name,
                    validation.data,
                    state,
                    {
                        durationMs: Date.now() - startMs,
                        isError: true,
                        errorMessage: error instanceof Error ? error.message : String(error),
                    },
                    intentMeta
                )
            }

            void trackToolSpan(tool.name, state, {
                durationMs: Date.now() - startMs,
                isError: true,
                errorMessage: error instanceof Error ? error.message : String(error),
                input: validation.data,
            })

            const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
            return handleToolError(error, tool.name, state.distinctId, sessionUuid)
        }
    }

    private async callExecTool(
        params: Record<string, unknown> | undefined,
        state: ResolvedState,
        intentMeta?: ToolCallIntentMeta
    ): Promise<unknown> {
        const execMetrics: ExecMetricState = { innerToolName: undefined, commandMeta: undefined }
        const resolved = this.resolveExecTool(state, execMetrics, intentMeta)

        const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
        const validation = resolved.schema.safeParse(toolArgs, { reportInput: true })
        if (!validation.success) {
            toolCallsTotal.inc({ tool: 'exec', status: 'validation_error' })
            return {
                content: [{ type: 'text', text: formatInputValidationError(resolved.name, validation.error) }],
                isError: true,
            }
        }

        const startMs = Date.now()

        // In single-exec mode every transport-level call is `exec`, so `$mcp_tool_name`
        // would always read `exec` and hide which tool the agent actually invoked.
        // Attribute the canonical event to the inner tool that dispatched (captured by
        // `trackInnerCall` above) — keeping the same standard `$mcp_tool_name` the SDK
        // emits for direct calls, so exec-routed and direct calls share one vocabulary.
        // `$mcp_mode` already distinguishes single-exec from direct for anyone who needs
        // it. Non-`call` verbs (tools/info/search/schema) resolve no inner tool and stay
        // attributed to `exec`.
        const execToolName = (): string => execMetrics.innerToolName ?? 'exec'

        // Which verb ran and which tool it targeted. Stamped on every exec event —
        // success and failure alike — so the discovery verbs stop collapsing into
        // one opaque `exec` bucket and an `info <tool>` can be linked to the
        // `call <tool>` that follows it.
        const execShape = execCommandAnalyticsProperties(validation.data, state)
        // Which stored skill an exec-routed read returned. Success only, unlike the
        // verb above: that records what the agent attempted, this records what it got.
        const execSkillShape = execSkillAnalyticsProperties(validation.data)

        try {
            const handlerResult = await resolved.handler(state.context, validation.data)
            const duration = Date.now() - startMs

            const response = isToolCallPayload(handlerResult)
                ? handlerResult
                : buildToolResultPayload({
                      handlerResult,
                      toolMeta: resolved._meta,
                      toolName: 'exec',
                      params: validation.data,
                      suppressStructuredContentForFormattedResults: state.clientProfile.isCliModeEnabled(),
                      distinctId: undefined,
                  })

            void trackToolCall(
                execToolName(),
                duration,
                false,
                state,
                {
                    ...execShape,
                    ...execSkillShape,
                    input_tokens: estimateTokens(validation.data),
                    output_tokens: estimateResponseTokens(response),
                    ...execMetrics.commandMeta,
                },
                intentMeta,
                this.servedToolDescription(execToolName())
            )

            return response
        } catch (error: unknown) {
            const metricTool = execToolName()
            const classification = classifyToolError(error, metricTool)
            if (!execMetrics.innerToolName) {
                // Match the inner-tool path, which labels rejected input `validation_error`.
                const status = classification.errorType === 'validation' ? 'validation_error' : 'error'
                toolCallsTotal.inc({ tool: 'exec', status })
            }

            void trackToolCall(
                metricTool,
                Date.now() - startMs,
                true,
                state,
                { ...execShape, ...errorAnalyticsProperties(classification, error), ...execMetrics.commandMeta },
                intentMeta,
                this.servedToolDescription(metricTool)
            )

            const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
            // Attribute the failure to the inner tool that actually ran (e.g. `query-logs`),
            // not the `exec` wrapper — so the agent-facing `[tool]` label and the 5xx
            // exception fingerprint point at the real source instead of collapsing every
            // exec-routed failure into one opaque `exec` bucket.
            return handleToolError(error, metricTool, state.distinctId, sessionUuid)
        }
    }

    /**
     * Third-party MCP tools for this caller, or none if the gateway can't be reached.
     * Swallows failures on purpose: a connected server having a bad day must not stop
     * PostHog's own tools from working.
     */
    private async gatewayToolsFor(state: ResolvedState): Promise<Tool<ZodObjectAny>[]> {
        const projectId = await state.context.stateManager.getProjectId().catch(() => undefined)
        if (!projectId) {
            return []
        }
        try {
            return await resolveGatewayTools(state.context, projectId)
        } catch (error) {
            console.warn('[gateway-tools] failed to resolve connected MCP tools', error)
            return []
        }
    }

    private resolveExecTool(
        state: ResolvedState,
        execMetrics: ExecMetricState,
        intentMeta?: ToolCallIntentMeta
    ): ResolvedTool {
        const commandReference = this.instructionsBuilder.buildExecCommandReference(state)

        const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
            // Record which inner tool actually dispatched so `callExecTool` can attribute
            // the canonical `$mcp_tool_call` event to the real tool instead of the `exec`
            // dispatcher. The PostHog event is intentionally NOT emitted here: the wrapper
            // event (now relabelled to the inner tool name, with the inner tool's category
            // derived from it) already carries this call, so a second emit would double-count.
            execMetrics.innerToolName = toolName
            const status = properties.success ? 'success' : properties.validation_error ? 'validation_error' : 'error'
            toolCallsTotal.inc({ tool: toolName, status })
            // Mirror the native path: schema rejections never start a handler, so
            // they get no duration observation (`callTool` starts its timer only
            // after validation passes).
            if (!properties.validation_error) {
                toolCallDurationSeconds.observe({ tool: toolName, status }, properties.duration_ms / 1000)
            }
            if (toolName === EXECUTE_SQL_TOOL_NAME && properties.input) {
                void trackExecuteSqlGeneration(
                    toolName,
                    properties.input,
                    state,
                    {
                        durationMs: properties.duration_ms,
                        isError: !properties.success,
                        errorMessage: properties.error_message,
                    },
                    intentMeta
                )
            }
            void trackToolSpan(toolName, state, {
                durationMs: properties.duration_ms,
                isError: !properties.success,
                errorMessage: properties.error_message,
                input: properties.input,
                output: properties.output,
            })
        }
        const clientContext = getEffectiveMCPClientContext(state.requestContext, state.sessionContext)

        // CLI `info execute-sql` returns the tool's static description from the catalog.
        // Override it with the same prompt tools-mode advertises, so the
        // information_schema schema-discovery steering matches across both modes.
        const execTools = state.allTools.map((tool) =>
            tool.name === EXECUTE_SQL_TOOL_NAME
                ? {
                      ...tool,
                      description: this.instructionsBuilder.formatExecuteSqlDescription(),
                  }
                : tool
        )

        const execTool = createExecTool(
            execTools,
            state.context,
            this.instructionsBuilder.buildExecToolDescription(),
            commandReference,
            clientContext.mcpConsumer,
            trackInnerCall,
            state.scopeGatedTools,
            {
                isInlineExecUiHost: state.clientProfile.isInlineExecUiHost(),
                helpCatalog: this.instructionsBuilder.buildExecHelpCatalog(state),
                ...(state.gatewayToolsEnabled ? { gatewayToolsProvider: () => this.gatewayToolsFor(state) } : {}),
                // A verb-only report lands first; `search` then reports again with its query
                // and counts. Merge so the richer report wins without losing the verb.
                trackCommand: (meta) => {
                    execMetrics.commandMeta = { ...execMetrics.commandMeta, ...meta }
                },
            }
        )

        return {
            name: 'exec',
            schema: execTool.schema,
            handler: (ctx, args) => execTool.handler(ctx, args as { command: string }),
            _meta: execTool._meta,
        }
    }

    private async callRenderUiTool(
        params: Record<string, unknown> | undefined,
        state: ResolvedState,
        intentMeta?: ToolCallIntentMeta
    ): Promise<unknown> {
        const renderUiTool = createRenderUiTool(state.allTools, state.context)
        if (!renderUiTool) {
            return {
                content: [{ type: 'text', text: 'render-ui is not available — no tool has a UI app' }],
                isError: true,
            }
        }

        const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
        const validation = renderUiTool.schema.safeParse(toolArgs)
        if (!validation.success) {
            toolCallsTotal.inc({ tool: 'render-ui', status: 'validation_error' })
            return { content: [{ type: 'text', text: `Invalid input: ${validation.error.message}` }], isError: true }
        }

        const stop = toolCallDurationSeconds.startTimer({ tool: 'render-ui' })
        const startMs = Date.now()
        try {
            const handlerResult = await renderUiTool.handler(state.context, validation.data)
            toolCallsTotal.inc({ tool: 'render-ui', status: 'success' })
            stop({ status: 'success' })
            void trackToolCall('render-ui', Date.now() - startMs, false, state, undefined, intentMeta)
            // The handler always returns an exec-built payload (UI resourceUri + structuredContent).
            return handlerResult
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: 'render-ui', status: 'error' })
            stop({ status: 'error' })
            const classification = classifyToolError(error, 'render-ui')
            void trackToolCall(
                'render-ui',
                Date.now() - startMs,
                true,
                state,
                errorAnalyticsProperties(classification, error),
                intentMeta
            )
            const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
            return handleToolError(error, 'render-ui', state.distinctId, sessionUuid)
        }
    }
}

type ToolErrorType =
    | 'missing_context'
    | 'validation'
    | 'permission'
    | 'timeout'
    | 'rate_limited'
    | 'api_5xx'
    | 'api_4xx'
    | 'internal'

interface ToolErrorClassification {
    errorType: ToolErrorType
    /** Upstream HTTP status, when the failure came from a PostHog API error. */
    status?: number
    /** Value-free descriptors of a schema rejection (offending field+code). */
    validationFields?: string[]
    /** Top-level keys the caller sent — surfaces unaccepted aliases on a union rejection. */
    validationInputKeys?: string[]
    /** Machine-readable leaf failure code: the API's validation error code or the exec rejection reason. */
    errorCode?: string
    /** Field path the API's validation error pointed at, array indexes normalized to `N`. */
    errorField?: string
}

/**
 * Buckets a thrown tool error into a low-cardinality category, increments the
 * Prometheus counter, and returns the classification so the caller can also
 * surface it on the `$mcp_tool_call` event (`$mcp_error_type` / `$mcp_error_status`).
 * Without that, the MCP analytics dashboard only sees the `$mcp_is_error`
 * boolean and can't break failures down by reason.
 */
function classifyToolError(error: unknown, toolName: string): ToolErrorClassification {
    const classification = resolveToolErrorClassification(error)
    toolErrorsTotal.inc({ tool: toolName, error_type: classification.errorType })
    return classification
}

function resolveToolErrorClassification(error: unknown): ToolErrorClassification {
    if (error instanceof MissingProjectContextError || error instanceof MissingOrganizationContextError) {
        return { errorType: 'missing_context' }
    }
    if (error instanceof ToolInputValidationError) {
        return {
            errorType: 'validation',
            ...(error.fields.length ? { validationFields: error.fields } : {}),
            ...(error.inputKeys.length ? { validationInputKeys: error.inputKeys } : {}),
        }
    }
    // Agent-recoverable command mistakes, so keep them out of the `internal` rate
    // ops alerts on. `missing_scope` is the exception: no input the agent sends
    // fixes it, the connection has to be reauthorized.
    if (error instanceof ExecCommandError) {
        return {
            errorType: error.reason === 'missing_scope' ? 'permission' : 'validation',
            errorCode: error.reason,
        }
    }
    if (findPostHogPermissionError(error)) {
        return { errorType: 'permission' }
    }
    if (error instanceof Error && error.name === 'TimeoutError') {
        return { errorType: 'timeout' }
    }

    const apiError = findRecoverableApiError(error)
    if (apiError instanceof PostHogValidationError) {
        const errorCode = apiError.code ? sanitizeErrorToken(apiError.code) : undefined
        const errorField = apiError.attr ? normalizeErrorField(apiError.attr) : undefined
        // Same descriptor property and format as a local schema rejection, so one
        // query covers both layers. There is no `validationInputKeys` counterpart:
        // the request body reached the API, so the keys it carried aren't ours to
        // reconstruct here.
        return {
            errorType: 'validation',
            validationFields: describeApiValidationError(apiError.attr, apiError.code),
            ...(errorCode ? { errorCode } : {}),
            ...(errorField ? { errorField } : {}),
        }
    }
    if (apiError instanceof PostHogApiError && apiError.status === 429) {
        return { errorType: 'rate_limited', status: apiError.status }
    }
    if (apiError instanceof PostHogApiError && apiError.status >= 500) {
        return { errorType: 'api_5xx', status: apiError.status }
    }
    if (apiError instanceof PostHogApiError) {
        return { errorType: 'api_4xx', status: apiError.status }
    }
    return { errorType: 'internal' }
}

// Mirrors the SDK's MAX_ERROR_MESSAGE_LENGTH so `$mcp_error_message` stays within
// the bound external servers get when they pass `error` to the SDK.
const MAX_ERROR_MESSAGE_LENGTH = 2048

// Matches the truncation the MCP analytics queries apply to `$mcp_error_type`.
const MAX_ERROR_TOKEN_LENGTH = 200

/**
 * DRF error codes and attrs are server-generated (field names and error codes,
 * never caller values), but they cross a network boundary — strip control
 * characters and cap length so a malformed body can't pollute the property.
 */
function sanitizeErrorToken(token: string): string | undefined {
    const sanitized = token
        .replace(/[\x00-\x1f\x7f]/g, '')
        .trim()
        .slice(0, MAX_ERROR_TOKEN_LENGTH)
    return sanitized || undefined
}

/**
 * Collapses array indexes in a DRF attr path (`actions__2__inputs__email`) to
 * `N` so one leaf failure mode groups to one value regardless of where in the
 * payload it occurred.
 */
function normalizeErrorField(attr: string): string | undefined {
    return sanitizeErrorToken(attr.replace(/(^|__)\d+(?=__|$)/g, '$1N'))
}

/**
 * Extracts a capturable message from a thrown value, restricted to an allowlist
 * of error classes whose message shape we control. `$mcp_error_message` is
 * readable by every analytics viewer in the project — not just the caller that
 * received the tool result — so arbitrary `Error.message`s and thrown strings
 * are never captured: tools echo caller input into them (document previews, SQL
 * fragments) and `PostHogApiError`'s default message embeds the upstream
 * response body. API errors are rebuilt from status + method + URL path instead.
 */
function extractErrorMessage(error: unknown): string | undefined {
    const raw = resolveSafeErrorMessage(error)
    if (!raw) {
        return undefined
    }
    // Strip control characters except newline/tab (multi-line validation errors stay readable)
    const sanitized = raw
        .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '')
        .trim()
        .slice(0, MAX_ERROR_MESSAGE_LENGTH)
    return sanitized || undefined
}

function resolveSafeErrorMessage(error: unknown): string | undefined {
    // Static recovery walkthroughs generated by our own constructors.
    if (error instanceof MissingProjectContextError || error instanceof MissingOrganizationContextError) {
        return error.message
    }
    // Documented value-free: offending field paths + issue codes, never input values.
    if (error instanceof ToolInputValidationError) {
        return error.message
    }
    // Value-free: the reason enum only. The dispatcher's human message can echo the
    // caller's tool name or a JSON-parser fragment, so it's never captured.
    if (error instanceof ExecCommandError) {
        return `Exec command rejected: ${error.reason}`
    }
    if (error instanceof Error && error.name === 'TimeoutError') {
        return 'Tool call timed out'
    }
    const apiError = findRecoverableApiError(error)
    if (apiError instanceof PostHogValidationError) {
        // `detail` is the raw API validation body; for query tools it echoes the caller's
        // offending HogQL/filter expression (`/query/` resolver errors quote the bad name),
        // so capture only the controlled code + field, never the free-text detail.
        const code = apiError.code ? `: ${apiError.code}` : ''
        const field = apiError.attr ? ` (field: ${apiError.attr})` : ''
        return `Validation error${code}${field}`
    }
    if (apiError instanceof PostHogApiError) {
        // Rebuilt summary: no response body, no query string.
        return `HTTP ${apiError.status} ${apiError.statusText} on ${apiError.method} ${safeUrlPath(apiError.url)}`
    }
    return undefined
}

function safeUrlPath(url: string): string {
    try {
        return new URL(url).pathname
    } catch {
        return ''
    }
}

/**
 * Properties stamped onto an errored `$mcp_tool_call` so the dashboard can slice
 * failures by reason. `$mcp_error_type` aligns with the SDK's native field; the
 * SDK derives a generic type from the thrown error when none is supplied, and an
 * explicit value here overrides it. `$mcp_error_message` carries a sanitized,
 * allowlisted summary of the failure (see `extractErrorMessage`) so tool-quality
 * drill-downs can show what went wrong without persisting caller-derived text.
 * `$mcp_error_code` / `$mcp_error_field` carry the machine-readable leaf failure
 * mode (error code + normalized field path, never values) so validation failures
 * are measurable per field instead of one undifferentiated `validation` bucket.
 */
function errorAnalyticsProperties(classification: ToolErrorClassification, error: unknown): Record<string, unknown> {
    const message = extractErrorMessage(error)
    return {
        $mcp_error_type: classification.errorType,
        ...(classification.status !== undefined ? { $mcp_error_status: classification.status } : {}),
        ...(classification.validationFields?.length ? { $mcp_validation_fields: classification.validationFields } : {}),
        ...(classification.validationInputKeys?.length
            ? { $mcp_validation_input_keys: classification.validationInputKeys }
            : {}),
        ...(classification.errorCode ? { $mcp_error_code: classification.errorCode } : {}),
        ...(classification.errorField ? { $mcp_error_field: classification.errorField } : {}),
        ...(message !== undefined ? { $mcp_error_message: message } : {}),
    }
}

/**
 * Properties describing the exec command itself: `$mcp_exec_verb` (which
 * dispatcher verb ran) and `$mcp_exec_target_tool` (the tool `info`/`schema`/
 * `call` named).
 *
 * `$mcp_tool_name` already carries the inner tool for a successful `call`, but
 * it reads `exec` for every other verb and for a `call` that never resolved — so
 * schema discovery, tool search, and a mistyped verb are indistinguishable, and
 * an `unknown_tool` rejection records nothing about what was attempted. Both
 * values are value-free by construction (see `describeExecCommand`): the verb comes
 * from the closed grammar and the target from this connection's own catalog, so a
 * token outside either is recorded as unrecognized rather than echoed.
 */
function execCommandAnalyticsProperties(execArgs: unknown, state: ResolvedState): Record<string, unknown> {
    const command = (execArgs as { command?: unknown } | undefined)?.command
    if (typeof command !== 'string') {
        return {}
    }
    const { verb, targetTool } = describeExecCommand(
        command,
        (name) => state.allTools.some((t) => t.name === name) || state.scopeGatedTools.some((t) => t.name === name)
    )
    return {
        ...(verb !== undefined ? { $mcp_exec_verb: verb } : {}),
        ...(targetTool !== undefined ? { $mcp_exec_target_tool: targetTool } : {}),
    }
}

/**
 * The skill properties for an exec-routed read, recovered from the command string.
 *
 * In single-exec mode the inner tool's arguments never arrive as tool arguments —
 * they are JSON inside `command` — so the direct-mode wiring alone would miss the
 * skill reads that arrive this way, which is nearly all of them. Reads the command with the
 * dispatcher's own parsers so analytics sees exactly the arguments the handler runs.
 */
function execSkillAnalyticsProperties(execArgs: unknown): Record<string, unknown> {
    const command = (execArgs as { command?: unknown } | undefined)?.command
    if (typeof command !== 'string') {
        return {}
    }
    return skillAnalyticsProperties(parseExecCallInnerToolName(command), parseExecCallInnerArgs(command))
}
