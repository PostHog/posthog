import { buildToolResultPayload, isToolCallPayload } from '@/lib/build-tool-result'
import { handleToolError } from '@/lib/errors'
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'
import { SessionManager } from '@/lib/SessionManager'
import { createExecTool, type ExecInnerCallTracker } from '@/tools/exec'

import { toolCallDurationSeconds, toolCallsTotal } from '../metrics'
import type { ToolCatalog } from '../tool-catalog'

import type { InstructionsBuilder } from './instructions'
import type { PreBuiltToolEntry, ResolvedState } from './types'

export class ToolExecutor {
    private readonly catalog: ToolCatalog
    private readonly instructionsBuilder: InstructionsBuilder

    constructor(catalog: ToolCatalog, instructionsBuilder: InstructionsBuilder) {
        this.catalog = catalog
        this.instructionsBuilder = instructionsBuilder
    }

    async handleToolsList(state: ResolvedState, props: RequestProperties): Promise<{ tools: PreBuiltToolEntry[] }> {
        if (state.useSingleExec) {
            return { tools: [this.instructionsBuilder.buildExecToolEntry(state, props)] }
        }

        const nameSet = new Set(state.allTools.map((t) => t.name))
        let filteredTools = this.catalog.getPreBuiltEntries().filter((e) => nameSet.has(e.name))

        if (state.version === 2) {
            filteredTools = filteredTools.map((entry) => {
                if (entry.name === 'execute-sql') {
                    return {
                        ...entry,
                        description: this.instructionsBuilder.formatExecuteSqlDescription(),
                    }
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
            return this._handleExecToolCall(params, state, props)
        }

        const preBuilt = this.catalog.getToolByName(toolName)
        if (!preBuilt) {
            toolCallsTotal.inc({ tool: toolName, status: 'error' })
            return { content: [{ type: 'text', text: `Tool ${toolName} not found` }], isError: true }
        }

        const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
        const validation = preBuilt.base.schema.safeParse(toolArgs)
        if (!validation.success) {
            toolCallsTotal.inc({ tool: toolName, status: 'validation_error' })
            return { content: [{ type: 'text', text: `Invalid input: ${validation.error.message}` }] }
        }

        const stop = toolCallDurationSeconds.startTimer({ tool: toolName })

        try {
            const isContextSwitch = toolName === 'switch-project' || toolName === 'switch-organization'
            const previousContext = isContextSwitch
                ? await state.reqCtx.getAnalyticsContextSafe(state.context)
                : undefined

            const handlerResult = await preBuilt.base.handler(state.context, validation.data)

            if (isContextSwitch) {
                void state.reqCtx.trackContextSwitchEvent(toolName, state.context, previousContext)
            }

            toolCallsTotal.inc({ tool: toolName, status: 'success' })
            stop({ status: 'success' })

            if (isToolCallPayload(handlerResult)) {
                return handlerResult
            }

            const hasUiResource = !!preBuilt.base._meta?.ui?.resourceUri
            const needsDistinctId = hasUiResource && typeof handlerResult !== 'string'
            const distinctId = needsDistinctId ? state.distinctId : undefined

            return buildToolResultPayload({
                handlerResult,
                toolMeta: preBuilt.base._meta,
                toolName,
                params: validation.data,
                clientName: props.mcpClientName,
                distinctId,
            })
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: toolName, status: 'error' })
            stop({ status: 'error' })
            const sessionUuid = props.sessionId
                ? await new SessionManager(state.reqCtx.cache).getSessionUuid(props.sessionId)
                : undefined
            return handleToolError(error, toolName, state.distinctId, sessionUuid)
        }
    }

    private async _handleExecToolCall(
        params: Record<string, unknown> | undefined,
        state: ResolvedState,
        props: RequestProperties
    ): Promise<unknown> {
        const stop = toolCallDurationSeconds.startTimer({ tool: 'exec' })

        try {
            const commandReference = this.instructionsBuilder.buildExecCommandReference(state)

            const trackInnerCall: ExecInnerCallTracker = (toolName, properties) => {
                void (async () => {
                    const freshContext = await state.reqCtx.getAnalyticsContextSafe(state.context)
                    await state.reqCtx._trackEvent(
                        AnalyticsEvent.MCP_TOOL_CALL,
                        { tool_name: toolName, ...properties },
                        freshContext,
                        undefined,
                        state.distinctId,
                        props
                    )
                })()
            }

            const execToolDescription = this.instructionsBuilder.buildExecToolDescription()

            const execTool = createExecTool(
                state.allTools,
                state.context,
                execToolDescription,
                commandReference,
                props.mcpConsumer,
                trackInnerCall
            )

            const toolArgs = (params?.arguments ?? {}) as Record<string, unknown>
            const validation = execTool.schema.safeParse(toolArgs)
            if (!validation.success) {
                toolCallsTotal.inc({ tool: 'exec', status: 'validation_error' })
                stop({ status: 'error' })
                return { content: [{ type: 'text', text: `Invalid input: ${validation.error.message}` }] }
            }

            const result = await execTool.handler(state.context, validation.data)

            toolCallsTotal.inc({ tool: 'exec', status: 'success' })
            stop({ status: 'success' })

            if (isToolCallPayload(result)) {
                return result
            }

            return buildToolResultPayload({
                handlerResult: result,
                toolMeta: execTool._meta,
                toolName: 'exec',
                params: validation.data,
                clientName: props.mcpClientName,
            })
        } catch (error: unknown) {
            toolCallsTotal.inc({ tool: 'exec', status: 'error' })
            stop({ status: 'error' })
            const sessionUuid = props.sessionId
                ? await new SessionManager(state.reqCtx.cache).getSessionUuid(props.sessionId)
                : undefined
            return handleToolError(error, 'exec', state.distinctId, sessionUuid)
        }
    }
}
