import type { ListToolsResult } from '@modelcontextprotocol/sdk/types.js'

import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import {
    handleToolError,
    MissingOrganizationContextError,
    MissingProjectContextError,
    PostHogApiError,
    PostHogValidationError,
    findPostHogPermissionError,
    findRecoverableApiError,
} from '@/lib/errors'
import { createExecTool, parseExecCommandKind, type ExecInnerCallTracker } from '@/tools/exec'
import { createRenderUiTool } from '@/tools/render-ui'
import type { Context, ZodObjectAny } from '@/tools/types'

import { trackExecCommand, trackToolCall } from './analytics'
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
}

export class ToolExecutor {
    private readonly catalog: ToolCatalog
    private readonly instructionsBuilder: InstructionsBuilder

    constructor(catalog: ToolCatalog, instructionsBuilder: InstructionsBuilder) {
        this.catalog = catalog
        this.instructionsBuilder = instructionsBuilder
    }

    async handleToolsList(state: ResolvedState): Promise<ListToolsResult> {
        if (state.useSingleExec) {
            const renderUiEntry = state.renderUiEnabled ? this.instructionsBuilder.buildRenderUiToolEntry(state) : null
            return {
                tools: [this.instructionsBuilder.buildExecToolEntry(state), ...(renderUiEntry ? [renderUiEntry] : [])],
            }
        }

        const nameSet = new Set(state.allTools.map((t) => t.name))
        const filteredTools = this.catalog.getPreBuiltEntries().filter((e) => nameSet.has(e.name))

        const withSqlDescription = filteredTools.map((entry) => {
            if (entry.name === 'execute-sql') {
                return { ...entry, description: this.instructionsBuilder.formatExecuteSqlDescription() }
            }
            return entry
        })

        return { tools: withSqlDescription }
    }

    async handleToolCall(params: Record<string, unknown> | undefined, state: ResolvedState): Promise<unknown> {
        const toolName = params?.name as string
        if (!toolName) {
            return { content: [{ type: 'text', text: 'Missing tool name' }], isError: true }
        }

        if (toolName === 'exec') {
            return this.callExecTool(params, state)
        }

        if (toolName === 'render-ui') {
            // render-ui is only advertised when the flag is on; reject calls otherwise.
            if (!state.renderUiEnabled) {
                toolCallsTotal.inc({ tool: toolName, status: 'error' })
                return { content: [{ type: 'text', text: `Tool ${toolName} not found` }], isError: true }
            }
            return this.callRenderUiTool(params, state)
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
            params,
            state
        )
    }

    private async callTool(
        tool: ResolvedTool,
        params: Record<string, unknown> | undefined,
        state: ResolvedState
    ): Promise<unknown> {
        const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
        const validation = tool.schema.safeParse(toolArgs)
        if (!validation.success) {
            toolCallsTotal.inc({ tool: tool.name, status: 'validation_error' })
            return { content: [{ type: 'text', text: `Invalid input: ${validation.error.message}` }], isError: true }
        }

        const stop = toolCallDurationSeconds.startTimer({ tool: tool.name })
        const startMs = Date.now()

        try {
            const isContextSwitch = tool.name === 'switch-project' || tool.name === 'switch-organization'
            const previousContext = isContextSwitch
                ? await state.reqCtx.getAnalyticsContextSafe(state.context)
                : undefined

            const handlerResult = await tool.handler(state.context, validation.data)

            if (isContextSwitch) {
                void state.reqCtx.trackContextSwitchEvent(tool.name, state.context, previousContext)
            }

            toolCallsTotal.inc({ tool: tool.name, status: 'success' })
            stop({ status: 'success' })

            void trackToolCall(tool.name, Date.now() - startMs, false, state)

            if (isToolCallPayload(handlerResult)) {
                return handlerResult
            }

            const hasUiResource = !!tool._meta?.ui?.resourceUri
            const needsDistinctId = hasUiResource && typeof handlerResult !== 'string'
            const distinctId = needsDistinctId ? state.distinctId : undefined

            return buildToolResultPayload({
                handlerResult,
                toolMeta: tool._meta,
                toolName: tool.name,
                params: validation.data,
                suppressStructuredContentForFormattedResults: state.clientProfile.isCliModeEnabled(),
                distinctId,
            })
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: tool.name, status: 'error' })
            stop({ status: 'error' })
            classifyToolError(error, tool.name)

            void trackToolCall(tool.name, Date.now() - startMs, true, state)

            const sessionUuid = await state.reqCtx.getSessionUuid(state.requestContext.sessionId)
            return handleToolError(error, tool.name, state.distinctId, sessionUuid)
        }
    }

    private async callExecTool(params: Record<string, unknown> | undefined, state: ResolvedState): Promise<unknown> {
        const execMetrics: ExecMetricState = { innerToolName: undefined }
        const resolved = this.resolveExecTool(state, execMetrics)

        const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
        const validation = resolved.schema.safeParse(toolArgs)
        if (!validation.success) {
            toolCallsTotal.inc({ tool: 'exec', status: 'validation_error' })
            return { content: [{ type: 'text', text: `Invalid input: ${validation.error.message}` }], isError: true }
        }

        const startMs = Date.now()

        try {
            const handlerResult = await resolved.handler(state.context, validation.data)

            // The underlying tool (if any) is attributed by `trackInnerCall` as its own
            // `mcp_tool_call`. Here we record the wrapper invocation itself as a separate
            // `mcp_exec_command` event so exec usage is countable without polluting tool stats.
            void trackExecCommand(state, {
                commandKind: parseExecCommandKind(validation.data.command),
                innerToolName: execMetrics.innerToolName,
                durationMs: Date.now() - startMs,
                isError: false,
            })

            if (isToolCallPayload(handlerResult)) {
                return handlerResult
            }

            return buildToolResultPayload({
                handlerResult,
                toolMeta: resolved._meta,
                toolName: 'exec',
                params: validation.data,
                suppressStructuredContentForFormattedResults: state.clientProfile.isCliModeEnabled(),
                distinctId: undefined,
            })
        } catch (error: unknown) {
            const metricTool = execMetrics.innerToolName ?? 'exec'
            if (!execMetrics.innerToolName) {
                toolCallsTotal.inc({ tool: 'exec', status: 'error' })
            }
            classifyToolError(error, metricTool)

            void trackExecCommand(state, {
                commandKind: parseExecCommandKind(validation.data.command),
                innerToolName: execMetrics.innerToolName,
                durationMs: Date.now() - startMs,
                isError: true,
            })

            const sessionUuid = await state.reqCtx.getSessionUuid(state.requestContext.sessionId)
            // Attribute the failure to the inner tool that actually ran (e.g. `query-logs`),
            // not the `exec` wrapper — so the agent-facing `[tool]` label and the 5xx
            // exception fingerprint point at the real source instead of collapsing every
            // exec-routed failure into one opaque `exec` bucket.
            return handleToolError(error, metricTool, state.distinctId, sessionUuid)
        }
    }

    private resolveExecTool(state: ResolvedState, execMetrics: ExecMetricState): ResolvedTool {
        const commandReference = this.instructionsBuilder.buildExecCommandReference(state)

        const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
            execMetrics.innerToolName = toolName
            const status = properties.success ? 'success' : 'error'
            toolCallsTotal.inc({ tool: toolName, status })
            toolCallDurationSeconds.observe({ tool: toolName, status }, properties.duration_ms / 1000)

            // Emit the SAME `mcp_tool_call` shape as the native path (including the
            // category), tagged `$mcp_via_exec` so the inner tool is attributed
            // correctly while the dashboard can still slice exec-routed traffic
            // without exec masquerading as a tool name.
            void trackToolCall(toolName, properties.duration_ms, !properties.success, state, {
                $mcp_via_exec: true,
                output_format: properties.output_format,
                ...(properties.error_message ? { error_message: properties.error_message } : {}),
            })
        }
        const clientContext = getEffectiveMCPClientContext(state.requestContext, state.sessionContext)

        const execTool = createExecTool(
            state.allTools,
            state.context,
            this.instructionsBuilder.buildExecToolDescription(),
            commandReference,
            clientContext.mcpConsumer,
            trackInnerCall,
            state.scopeGatedTools
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
        state: ResolvedState
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
            void trackToolCall('render-ui', Date.now() - startMs, false, state)
            // The handler always returns an exec-built payload (UI resourceUri + structuredContent).
            return handlerResult
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: 'render-ui', status: 'error' })
            stop({ status: 'error' })
            classifyToolError(error, 'render-ui')
            void trackToolCall('render-ui', Date.now() - startMs, true, state)
            const sessionUuid = await state.reqCtx.getSessionUuid(state.requestContext.sessionId)
            return handleToolError(error, 'render-ui', state.distinctId, sessionUuid)
        }
    }
}

function classifyToolError(error: unknown, toolName: string): void {
    if (error instanceof MissingProjectContextError || error instanceof MissingOrganizationContextError) {
        toolErrorsTotal.inc({ tool: toolName, error_type: 'missing_context' })
    } else if (findPostHogPermissionError(error)) {
        toolErrorsTotal.inc({ tool: toolName, error_type: 'permission' })
    } else if (error instanceof Error && error.name === 'TimeoutError') {
        toolErrorsTotal.inc({ tool: toolName, error_type: 'timeout' })
    } else {
        const apiError = findRecoverableApiError(error)
        if (apiError instanceof PostHogValidationError) {
            toolErrorsTotal.inc({ tool: toolName, error_type: 'validation' })
        } else if (apiError instanceof PostHogApiError && apiError.status >= 500) {
            toolErrorsTotal.inc({ tool: toolName, error_type: 'api_5xx' })
        } else if (apiError instanceof PostHogApiError) {
            toolErrorsTotal.inc({ tool: toolName, error_type: 'api_4xx' })
        } else {
            toolErrorsTotal.inc({ tool: toolName, error_type: 'internal' })
        }
    }
}
