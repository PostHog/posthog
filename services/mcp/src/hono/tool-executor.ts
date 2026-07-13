import type { ListToolsResult } from '@modelcontextprotocol/sdk/types.js'

import classifierTableJson from '@/generated/code-exec/classifier-table.json'
import {
    buildToolResultPayload,
    estimateResponseTokens,
    isToolCallPayload,
    type ToolResultPayload,
} from '@/lib/build-tool-result'
import { type ClassifierTable, MemoryPlanStore, type PlanStore, RedisPlanStore } from '@/lib/code-exec'
import {
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
import { getPostHogClient } from '@/lib/posthog'
import { checkScript } from '@/tools/code-exec/compile-gate'
import { CODE_EXECUTION_FEATURE_FLAG, CODE_FIRST_FEATURE_FLAG } from '@/tools/code-exec/constants'
import { LocalVmExecutor, type SandboxExecutor } from '@/tools/code-exec/executor'
import {
    type CodeExecutionDiscovery,
    type CodeExecutionRuntime,
    createCodeExecutionDiscovery,
    createCodeExecutionRuntime,
    type InnerToolDispatcher,
} from '@/tools/code-exec/runtime'
import {
    createExecTool,
    dispatchInnerTool,
    formatInputValidationError,
    type ExecInnerCallTracker,
    type ExecVerbTracker,
} from '@/tools/exec'
import { EXECUTE_SQL_TOOL_NAME } from '@/tools/posthogAiTools/executeSql'
import { createRenderUiTool } from '@/tools/render-ui'
import type { Context, ZodObjectAny } from '@/tools/types'

import { trackExecuteSqlGeneration, trackToolCall, trackToolsList, type ToolCallIntentMeta } from './analytics'
import type { RedisLike } from './cache/RedisCache'
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
    /** Verb-dimension analytics (spec §4.6 Phase 0), accumulated via the `trackVerb` seam. */
    verb?: string
    runStatus?: string
    planMutations?: number
    fastPath?: boolean
    deprecatedVerb?: boolean
}

/**
 * Process-level dependencies of the code-execution verbs — the plan store and
 * executor are request-independent, so they are built once and reused across
 * `exec` calls. The executor is `null` where scripts cannot run (production
 * until the Modal pool, spec §3.3): the runtime still serves the no-sandbox
 * fast path there (spec §4.2).
 */
interface CodeExecutionSharedParts {
    planStore: PlanStore
    executor: SandboxExecutor | null
}

export class ToolExecutor {
    private readonly catalog: ToolCatalog
    private readonly instructionsBuilder: InstructionsBuilder
    private readonly redis: RedisLike | undefined
    private codeExecutionParts: CodeExecutionSharedParts | undefined

    constructor(catalog: ToolCatalog, instructionsBuilder: InstructionsBuilder, redis?: RedisLike) {
        this.catalog = catalog
        this.instructionsBuilder = instructionsBuilder
        this.redis = redis
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
            return {
                content: [{ type: 'text', text: formatInputValidationError(tool.name, validation.error) }],
                isError: true,
            }
        }

        const stop = toolCallDurationSeconds.startTimer({ tool: tool.name })
        const startMs = Date.now()

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
                    input_tokens: estimateTokens(validation.data),
                    output_tokens: estimateResponseTokens(response),
                },
                intentMeta
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
                errorAnalyticsProperties(classification),
                intentMeta
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

            const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
            return handleToolError(error, tool.name, state.distinctId, sessionUuid)
        }
    }

    private async callExecTool(
        params: Record<string, unknown> | undefined,
        state: ResolvedState,
        intentMeta?: ToolCallIntentMeta
    ): Promise<unknown> {
        const execMetrics: ExecMetricState = { innerToolName: undefined }
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
                    input_tokens: estimateTokens(validation.data),
                    output_tokens: estimateResponseTokens(response),
                    ...execVerbAnalyticsProperties(execMetrics),
                },
                intentMeta
            )

            return response
        } catch (error: unknown) {
            const metricTool = execToolName()
            if (!execMetrics.innerToolName) {
                toolCallsTotal.inc({ tool: 'exec', status: 'error' })
            }
            const classification = classifyToolError(error, metricTool)

            void trackToolCall(
                metricTool,
                Date.now() - startMs,
                true,
                state,
                { ...errorAnalyticsProperties(classification), ...execVerbAnalyticsProperties(execMetrics) },
                intentMeta
            )

            const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
            // Attribute the failure to the inner tool that actually ran (e.g. `query-logs`),
            // not the `exec` wrapper — so the agent-facing `[tool]` label and the 5xx
            // exception fingerprint point at the real source instead of collapsing every
            // exec-routed failure into one opaque `exec` bucket.
            return handleToolError(error, metricTool, state.distinctId, sessionUuid)
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
        }
        // Accumulate verb-dimension updates onto the shared metric state so both
        // trackToolCall paths (success and error) can stamp `$mcp_exec_*` properties.
        const trackVerb: ExecVerbTracker = (update) => {
            Object.assign(execMetrics, update)
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

        // Fast-path seam (spec §4.2): call-shaped `run` scripts dispatch through
        // the same pipeline as `call`, so attribution, UI payloads, and output
        // formatting stay byte-identical.
        const toolDispatcher: InnerToolDispatcher = {
            canDispatch: (toolName, input) => {
                const tool = execTools.find((t) => t.name === toolName)
                return tool !== undefined && tool.schema.safeParse(input).success
            },
            dispatch: async (toolName, input, opts) => {
                const tool = execTools.find((t) => t.name === toolName)
                if (!tool) {
                    throw new Error(`Tool "${toolName}" is not available in this session`)
                }
                return dispatchInnerTool({
                    tool,
                    context: state.context,
                    input,
                    mcpConsumer: clientContext.mcpConsumer,
                    isInlineExecUiHost: state.clientProfile.isInlineExecUiHost(),
                    trackInnerCall,
                    suppressUiPayload: opts?.suppressUiPayload,
                })
            },
        }

        const execTool = createExecTool(
            execTools,
            state.context,
            this.instructionsBuilder.buildExecToolDescription(state),
            commandReference,
            clientContext.mcpConsumer,
            trackInnerCall,
            state.scopeGatedTools,
            {
                isInlineExecUiHost: state.clientProfile.isInlineExecUiHost(),
                codeExecutionDiscovery: this.resolveCodeExecutionDiscovery(state),
                codeExecutionRuntime: this.resolveCodeExecutionRuntime(state, toolDispatcher),
                codeFirst: state.toolFeatureFlags?.[CODE_FIRST_FEATURE_FLAG] === true,
                trackVerb,
            }
        )

        return {
            name: 'exec',
            schema: execTool.schema,
            handler: (ctx, args) => execTool.handler(ctx, args as { command: string; script?: string }),
            _meta: execTool._meta,
        }
    }

    /**
     * The static-artifact half of the code-execution surface (spec §4.4):
     * `types` and the code-first aliases read only the generated discovery
     * index, so they are gated on the flag alone — never on whether this
     * process can execute scripts.
     */
    private resolveCodeExecutionDiscovery(state: ResolvedState): CodeExecutionDiscovery | undefined {
        if (state.toolFeatureFlags?.[CODE_EXECUTION_FEATURE_FLAG] !== true) {
            return undefined
        }
        return createCodeExecutionDiscovery({ sessionScopes: state.apiKeyScopes })
    }

    /**
     * Build the stateful code-execution runtime (`run`/`apply`) for this
     * request, or `undefined` when the `mcp-code-execution` flag is off. The
     * runtime is wired even where scripts can't execute (production until the
     * Modal sandbox pool, spec §3.3) — call-shaped scripts dispatch through
     * the no-sandbox fast path there, and everything else gets a targeted
     * sandbox-unavailable answer (spec §4.2).
     */
    private resolveCodeExecutionRuntime(
        state: ResolvedState,
        toolDispatcher: InnerToolDispatcher
    ): CodeExecutionRuntime | undefined {
        if (state.toolFeatureFlags?.[CODE_EXECUTION_FEATURE_FLAG] !== true) {
            return undefined
        }
        const parts = this.getCodeExecutionParts()
        return createCodeExecutionRuntime({
            realFetch: (input, init) => state.context.api.fetchRaw(input, init),
            // Same identity `confirmed_action` binds its tokens to.
            getSub: () => state.context.getDistinctId(),
            // Session project/org, exactly as the tool handlers resolve them —
            // keeps the sandbox and fast-path stacks on one target project and
            // pins plans to the project the user confirms.
            getProjectId: () => state.context.stateManager.getProjectId(),
            getOrgId: () => state.context.stateManager.getOrgID(),
            planStore: parts.planStore,
            ...(parts.executor ? { executor: parts.executor } : {}),
            // The server always injects the real typecheck gate — `typescript`
            // is bundle-external here and node_modules exists on the image.
            compileGate: { check: checkScript },
            toolDispatcher,
            // The generated artifact matches `ClassifierTable` field-for-field, but
            // JSON import inference widens the `idFields[].type` literals to string.
            classifierTable: classifierTableJson as unknown as ClassifierTable,
        })
    }

    private getCodeExecutionParts(): CodeExecutionSharedParts {
        if (this.codeExecutionParts === undefined) {
            this.codeExecutionParts = {
                // Without Redis this falls back to process memory: plans (and their
                // consumed tombstones) don't survive a restart and don't replicate —
                // single-replica (local dev / tests) only.
                planStore: this.redis ? new RedisPlanStore(this.redis) : new MemoryPlanStore(),
                executor: this.buildExecutor(),
            }
        }
        return this.codeExecutionParts
    }

    private buildExecutor(): SandboxExecutor | null {
        try {
            return new LocalVmExecutor()
        } catch (err) {
            console.error(
                `[mcp] no sandbox executor here — run/apply limited to the fast path (single-call scripts) — ${(err as Error).message}`
            )
            return null
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
                errorAnalyticsProperties(classification),
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
        return { errorType: 'validation' }
    }
    if (findPostHogPermissionError(error)) {
        return { errorType: 'permission' }
    }
    if (error instanceof Error && error.name === 'TimeoutError') {
        return { errorType: 'timeout' }
    }

    const apiError = findRecoverableApiError(error)
    if (apiError instanceof PostHogValidationError) {
        return { errorType: 'validation' }
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

/**
 * Properties stamped onto an errored `$mcp_tool_call` so the dashboard can slice
 * failures by reason. `$mcp_error_type` aligns with the SDK's native field; the
 * SDK derives a generic type from the thrown error when none is supplied, and an
 * explicit value here overrides it.
 */
function errorAnalyticsProperties(classification: ToolErrorClassification): Record<string, unknown> {
    return {
        $mcp_error_type: classification.errorType,
        ...(classification.status !== undefined ? { $mcp_error_status: classification.status } : {}),
    }
}

/**
 * Verb-dimension properties for the exec `$mcp_tool_call` event (spec §4.6
 * Phase 0): which verb dispatched, the structured run/apply outcome, plan
 * mutation count, and the fast-path flag. Every field is conditional — a
 * request that never reached the exec handler (schema rejection) stamps none.
 */
function execVerbAnalyticsProperties(metrics: ExecMetricState): Record<string, unknown> {
    return {
        ...(metrics.verb !== undefined ? { $mcp_exec_verb: metrics.verb } : {}),
        ...(metrics.runStatus !== undefined ? { $mcp_exec_run_status: metrics.runStatus } : {}),
        ...(metrics.planMutations !== undefined ? { $mcp_exec_plan_mutations: metrics.planMutations } : {}),
        ...(metrics.fastPath !== undefined ? { $mcp_exec_fast_path: metrics.fastPath } : {}),
        ...(metrics.deprecatedVerb !== undefined ? { $mcp_exec_deprecated_verb: metrics.deprecatedVerb } : {}),
    }
}
