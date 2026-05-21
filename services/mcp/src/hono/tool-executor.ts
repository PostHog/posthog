import type { ListToolsResult } from '@modelcontextprotocol/sdk/types.js'

import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import { handleToolError } from '@/lib/errors'
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'
import { createExecTool, type ExecInnerCallTracker } from '@/tools/exec'
import type { Context, ZodObjectAny } from '@/tools/types'

import { trackToolCall } from './analytics'
import type { InstructionsBuilder } from './instructions'
import { toolCallDurationSeconds, toolCallsTotal } from './metrics'
import type { ResolvedState } from './request-state-resolver'
import type { ToolCatalog } from './tool-catalog'

interface ResolvedTool {
    name: string
    schema: ZodObjectAny
    handler: (ctx: Context, args: unknown) => Promise<unknown>
    _meta?: { ui?: { resourceUri?: string }; [key: string]: unknown } | undefined
}

export class ToolExecutor {
    private readonly catalog: ToolCatalog
    private readonly instructionsBuilder: InstructionsBuilder

    constructor(catalog: ToolCatalog, instructionsBuilder: InstructionsBuilder) {
        this.catalog = catalog
        this.instructionsBuilder = instructionsBuilder
    }

    async handleToolsList(state: ResolvedState, props: RequestProperties): Promise<ListToolsResult> {
        if (state.useSingleExec) {
            return { tools: [this.instructionsBuilder.buildExecToolEntry(state, props)] }
        }

        const nameSet = new Set(state.allTools.map((t) => t.name))
        let filteredTools = this.catalog.getPreBuiltEntries().filter((e) => nameSet.has(e.name))

        if (state.version === 2) {
            filteredTools = filteredTools.map((entry) => {
                if (entry.name === 'execute-sql') {
                    return { ...entry, description: this.instructionsBuilder.formatExecuteSqlDescription() }
                }
                return entry
            })
        }

        return { tools: filteredTools }
    }

    async handleToolCall(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<unknown> {
        const toolName = params?.name as string
        if (!toolName) {
            return { content: [{ type: 'text', text: 'Missing tool name' }], isError: true }
        }

        if (state.useSingleExec && toolName === 'exec') {
            return this.callTool(this.resolveExecTool(state, props), params, props, state)
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
            props,
            state
        )
    }

    private async callTool(
        tool: ResolvedTool,
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
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

            void trackToolCall(tool.name, Date.now() - startMs, false, props, state)

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
                clientName: props.mcpClientName,
                distinctId,
            })
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: tool.name, status: 'error' })
            stop({ status: 'error' })

            void trackToolCall(tool.name, Date.now() - startMs, true, props, state)

            const sessionUuid = await state.reqCtx.getSessionUuid(props.sessionId)
            return handleToolError(error, tool.name, state.distinctId, sessionUuid)
        }
    }

    private resolveExecTool(state: ResolvedState, props: RequestProperties): ResolvedTool {
        const commandReference = this.instructionsBuilder.buildExecCommandReference(state)

        const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
            void (async () => {
                const freshContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
                await state.reqCtx.trackEvent(
                    AnalyticsEvent.MCP_TOOL_CALL,
                    { tool_name: toolName, ...properties },
                    freshContext,
                    undefined,
                    state.distinctId,
                    props
                )
            })().catch(() => {})
        }

        const execTool = createExecTool(
            state.allTools,
            state.context,
            this.instructionsBuilder.buildExecToolDescription(),
            commandReference,
            props.mcpConsumer,
            trackInnerCall
        )

        return {
            name: 'exec',
            schema: execTool.schema,
            handler: (ctx, args) => execTool.handler(ctx, args as { command: string }),
            _meta: execTool._meta,
        }
    }
}
