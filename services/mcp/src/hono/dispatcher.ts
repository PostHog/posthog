import {
    ErrorCode,
    JSONRPC_VERSION,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
} from '@modelcontextprotocol/sdk/types.js'
import type {
    CallToolRequest,
    GetPromptRequest,
    InitializeRequest,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    ListPromptsRequest,
    ListResourcesRequest,
    ListToolsRequest,
    PingRequest,
    ReadResourceRequest,
} from '@modelcontextprotocol/sdk/types.js'
import GUIDELINES from '@shared/guidelines.md'
import { randomUUID } from 'node:crypto'

import { mapErrorToAuthResponse } from '@/lib/auth-errors'
import { StateLookupCache } from '@/lib/cache/StateLookupCache'
import { isLegacyDialectOnlyClient } from '@/lib/client-detection'
import { MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { McpSessionResetRequiredError, SESSION_RESET_REQUIRED_REASON } from '@/lib/errors'
import { resolveFeatureFlagOverrides } from '@/lib/posthog/flags'
import type { RequestProperties } from '@/lib/request-properties'
import { getPublicUrl } from '@/lib/routing'
import {
    isModernRequest,
    META_SERVER_INFO,
    MODERN_PROTOCOL_VERSIONS,
    parseRequestProtocolMeta,
    readProtocolHeaders,
    SERVER_DISCOVER_METHOD,
    STATELESS_PROTOCOL_VERSION,
    validateModernRequest,
} from '@/lib/stateless-protocol'

import { trackInitEvent } from './analytics'
import type { RedisLike } from './cache/RedisCache'
import { getEnv, MCP_EXEC_SKILLS_FEATURE_FLAG } from './constants'
import { GuidanceEngine } from './guidance/engine'
import { InstructionsBuilder } from './instructions'
import { InterviewRecruitment, InterviewRequestError } from './interview-recruitment'
import { initDurationSeconds, initTotal } from './metrics'
import { RequestStateResolver, type ResolvedState } from './request-state-resolver'
import { ResourceCatalog } from './resource-catalog'
import { SkillCatalogService } from './skill-catalog-service'
import { ToolCatalog } from './tool-catalog'
import { ToolExecutor } from './tool-executor'

export { McpDispatcher }
export type { ResolvedState } from './request-state-resolver'

const MAX_BATCH_SIZE = 100
const MAX_BODY_BYTES = 1_048_576

const Method = {
    Initialize: 'initialize' as InitializeRequest['method'],
    Discover: SERVER_DISCOVER_METHOD,
    ToolsList: 'tools/list' as ListToolsRequest['method'],
    ToolsCall: 'tools/call' as CallToolRequest['method'],
    ResourcesList: 'resources/list' as ListResourcesRequest['method'],
    ResourcesRead: 'resources/read' as ReadResourceRequest['method'],
    PromptsList: 'prompts/list' as ListPromptsRequest['method'],
    PromptsGet: 'prompts/get' as GetPromptRequest['method'],
    Ping: 'ping' as PingRequest['method'],
} as const

const TRACKED_METHODS: Set<string> = new Set([Method.Initialize, Method.Discover, Method.ToolsList, Method.ToolsCall])

// Results the 2026-07-28 spec types as CacheableResult (required ttlMs +
// cacheScope). Everything here varies per token (scopes, flags, staff gating)
// or per user (discover instructions), so shared intermediaries must not cache.
const CACHEABLE_METHODS: Set<string> = new Set([
    Method.Discover,
    Method.ToolsList,
    Method.ResourcesList,
    Method.ResourcesRead,
    Method.PromptsList,
])
// ttlMs: 0 is the spec-compliant "don't serve from cache" (both fields are
// required on CacheableResult). Nonzero TTLs are production-only: SDK clients
// honor the hint with a built-in response cache, so locally it would serve a
// stale tools/list while iterating on tool definitions — and with
// listChanged: false the TTL is the client's only freshness signal.
const CACHEABLE_RESULT_TTL_MS = process.env.NODE_ENV === 'production' ? 60_000 : 0

const METHOD_NOT_FOUND = Symbol('method-not-found')

const SERVER_CAPABILITIES = {
    tools: { listChanged: false },
    resources: { listChanged: false },
    prompts: { listChanged: false },
    extensions: {
        // Tokens the authorization server issues for an enterprise IdP's ID-JAG are accepted here.
        'io.modelcontextprotocol/enterprise-managed-authorization': {},
    },
} as const

function isRequest(msg: JSONRPCMessage): msg is JSONRPCRequest {
    return (
        typeof msg === 'object' &&
        msg !== null &&
        'id' in msg &&
        typeof (msg as { method?: unknown }).method === 'string'
    )
}

// The SDK owns minting; only restore handles it accepts before resolving tool targets.
const SDK_CONVERSATION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function echoedConversationId(request: JSONRPCRequest): string | undefined {
    const value = (request.params?.arguments as { conversation_id?: unknown } | undefined)?.conversation_id
    const id = typeof value === 'string' ? value.trim().toLowerCase() : undefined
    return id && SDK_CONVERSATION_ID.test(id) ? id : undefined
}

type JsonRpcResultResponse = { jsonrpc: typeof JSONRPC_VERSION; id: number | string; result: unknown }
type JsonRpcErrorResponse = {
    jsonrpc: typeof JSONRPC_VERSION
    id: number | string
    error: { code: number; message: string; data?: unknown }
}
type JsonRpcResponse = JsonRpcResultResponse | JsonRpcErrorResponse

function jsonRpcResult(id: number | string, result: unknown): JsonRpcResultResponse {
    return { jsonrpc: JSONRPC_VERSION, id, result }
}

function jsonRpcMethodError(id: number | string, code: number, message: string, data?: unknown): JsonRpcErrorResponse {
    return { jsonrpc: JSONRPC_VERSION, id, error: { code, message, ...(data !== undefined ? { data } : {}) } }
}

function jsonRpcErrorResponse(id: unknown, code: number, message: string, data?: unknown, status = 200): Response {
    return new Response(
        JSON.stringify({
            jsonrpc: JSONRPC_VERSION,
            id: id ?? null,
            error: { code, message, ...(data !== undefined ? { data } : {}) },
        }),
        {
            status,
            headers: { 'Content-Type': 'application/json' },
        }
    )
}

class McpDispatcher {
    private readonly catalog: ToolCatalog
    private readonly resourceCatalog: ResourceCatalog
    private readonly stateResolver: RequestStateResolver
    private readonly toolExecutor: ToolExecutor
    private readonly instructionsBuilder: InstructionsBuilder
    private readonly skillCatalogService: SkillCatalogService
    private readonly interviewRecruitment: InterviewRecruitment

    private warmupPromise: Promise<void> | undefined

    constructor(catalog: ToolCatalog, redis: RedisLike) {
        const env = getEnv()
        this.catalog = catalog
        this.resourceCatalog = new ResourceCatalog(env, redis)
        this.stateResolver = new RequestStateResolver(catalog, redis, env)
        this.instructionsBuilder = new InstructionsBuilder(GUIDELINES)
        this.skillCatalogService = new SkillCatalogService(redis, {
            archiveUrl: env.POSTHOG_MCP_SKILLS_URL,
            expectedArchiveSha: env.POSTHOG_MCP_SKILLS_SHA256,
        })
        this.toolExecutor = new ToolExecutor(
            catalog,
            this.instructionsBuilder,
            this.skillCatalogService,
            new GuidanceEngine(redis)
        )
        this.interviewRecruitment = new InterviewRecruitment(redis)
    }

    async warmup(): Promise<void> {
        this.warmupPromise ??= this.doWarmup()
        await this.warmupPromise
    }

    private async doWarmup(): Promise<void> {
        await this.catalog.warmup()
        const skillsEnabled = resolveFeatureFlagOverrides()[MCP_EXEC_SKILLS_FEATURE_FLAG] !== false
        await Promise.all([
            this.resourceCatalog.warmup(),
            skillsEnabled ? this.skillCatalogService.warmup() : undefined,
        ])
        if (skillsEnabled) {
            // Skills refresh on a timer, never on a request: the July incident was every
            // handshake re-reading the archive from Redis.
            this.skillCatalogService.start()
        }
    }

    async handleRequest(req: Request, props: RequestProperties): Promise<Response> {
        const contentLength = req.headers.get('content-length')
        if (contentLength && parseInt(contentLength, 10) > MAX_BODY_BYTES) {
            return jsonRpcErrorResponse(null, ErrorCode.InvalidRequest, 'Request body too large')
        }

        let body: unknown
        try {
            body = await req.json()
        } catch {
            return jsonRpcErrorResponse(null, ErrorCode.ParseError, 'Parse error: Invalid JSON')
        }

        const wasArray = Array.isArray(body)
        const messages: JSONRPCMessage[] = wasArray ? (body as JSONRPCMessage[]) : [body as JSONRPCMessage]

        if (messages.length > MAX_BATCH_SIZE) {
            return jsonRpcErrorResponse(null, ErrorCode.InvalidRequest, 'Batch too large')
        }

        // SEP-2243 header validation, before any dispatch: modern messages must
        // carry matching operation headers, and (since JSON-RPC batching was
        // removed in 2025-06-18) can never arrive inside an array. Legacy
        // traffic takes neither branch and keeps its exact wire behavior.
        const protocolHeaders = readProtocolHeaders(req.headers)
        let singleModern = false
        if (wasArray) {
            const batchHasModern = messages.some((m) =>
                isModernRequest(protocolHeaders, parseRequestProtocolMeta((m as { params?: unknown }).params))
            )
            if (batchHasModern) {
                return jsonRpcErrorResponse(
                    null,
                    ErrorCode.InvalidRequest,
                    `JSON-RPC batching is not supported by protocol version ${STATELESS_PROTOCOL_VERSION}`,
                    undefined,
                    400
                )
            }
        } else {
            const message = messages[0]! as { id?: number | string; method?: unknown; params?: unknown }
            const protocolMeta = parseRequestProtocolMeta(message.params)
            singleModern = isModernRequest(protocolHeaders, protocolMeta)
            if (singleModern) {
                // Before header validation, so header-dropping bridges fall back to
                // `initialize` instead of dying on HeaderMismatch. HTTP 200, not the
                // spec's 404: mcp-remote's transport treats any non-2xx as fatal.
                if (message.method === Method.Discover && isLegacyDialectOnlyClient(protocolMeta.clientName)) {
                    return jsonRpcErrorResponse(message.id ?? null, ErrorCode.MethodNotFound, 'Method not found')
                }
                const validationError = validateModernRequest(protocolHeaders, message)
                if (validationError) {
                    return jsonRpcErrorResponse(
                        message.id ?? null,
                        validationError.code,
                        validationError.message,
                        validationError.data,
                        400
                    )
                }
            }
        }

        const requests = messages.filter(isRequest)
        if (requests.length === 0) {
            const responses = messages.filter((message) => this.interviewRecruitment.isLegacyResponse(message))
            if (!singleModern && responses.length > 0) {
                const state = await this.stateResolver.resolve(props)
                for (const response of responses) {
                    await this.interviewRecruitment.receiveLegacyResponse(response, state, props.userHash)
                }
            }
            return new Response(null, { status: 202 })
        }

        // Only the legacy dialect mints sessions — modern `initialize` is a
        // removed RPC and gets method-not-found in dispatch.
        const hasInit = !singleModern && requests.some((r) => r.method === Method.Initialize)
        if (hasInit) {
            props.mcpSessionId = randomUUID()
        }

        if (!props.mcpSessionId && requests.length === 1 && requests[0]!.method === Method.ToolsCall) {
            props.mcpConversationId = echoedConversationId(requests[0]!) ?? props.mcpConversationId
        }

        const carriedContextHandle = Boolean(props.mcpSessionId || props.mcpConversationId)
        const sessionlessBatch = wasArray && !props.mcpSessionId
        const lookups = sessionlessBatch ? new StateLookupCache() : undefined
        const needsState = !sessionlessBatch && requests.some((r) => TRACKED_METHODS.has(r.method))
        let state: ResolvedState | undefined
        try {
            state = needsState ? await this.stateResolver.resolve(props) : undefined
        } catch (error) {
            // A failed resolution still fails the handshake for the client, so count
            // it in mcp_init_total — otherwise MCPServerHighInitErrorRate only sees
            // failures past this point. Auth failures (expired tokens, missing scopes)
            // are client-side and dominate resolution errors, so they get their own
            // status to keep the alert on `status="error"` meaningful. The rethrow
            // surfaces as a 401/403/500 upstream via handleCatchError.
            if (hasInit) {
                initTotal.inc({ status: mapErrorToAuthResponse(error) ? 'auth_error' : 'error' })
            }
            // A JSON-RPC error with HTTP 200 reaches the agent, which can tell the user to
            // reconnect. Some transports, such as mcp-remote, treat any non-2xx status as fatal.
            if (error instanceof McpSessionResetRequiredError) {
                const errors = requests.map((r) =>
                    jsonRpcMethodError(r.id, ErrorCode.InvalidRequest, error.message, {
                        reason: SESSION_RESET_REQUIRED_REASON,
                    })
                )
                return new Response(JSON.stringify(!wasArray && errors.length === 1 ? errors[0] : errors), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            }
            throw error
        }

        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (props.mcpSessionId) {
            headers['Mcp-Session-Id'] = props.mcpSessionId
        }

        if (!wasArray && requests.length === 1) {
            let elicitation: JSONRPCRequest | undefined
            const canStream =
                !singleModern &&
                req.headers
                    .get('accept')
                    ?.split(',')
                    .some((value) => value.trim().split(';')[0] === 'text/event-stream')
            const result = await this.dispatch(
                requests[0]!,
                props,
                state,
                getPublicUrl(req).origin,
                carriedContextHandle,
                canStream
                    ? (request) => {
                          elicitation = request
                      }
                    : undefined
            )
            if (elicitation) {
                const body = [elicitation, result]
                    .map((message) => `event: message\ndata: ${JSON.stringify(message)}\n\n`)
                    .join('')
                return new Response(body, {
                    headers: { ...headers, 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
                })
            }
            // SEP-2575: unsupported RPCs get HTTP 404 in the modern dialect.
            const status =
                singleModern && 'error' in result && result.error.code === ErrorCode.MethodNotFound ? 404 : 200
            return new Response(JSON.stringify(result), { status, headers })
        }

        const results = await Promise.all(
            requests.map(async (request) => {
                if (!sessionlessBatch) {
                    return this.dispatch(request, props, state, getPublicUrl(req).origin, carriedContextHandle)
                }
                const itemProps = { ...props }
                if (request.method === Method.ToolsCall) {
                    itemProps.mcpConversationId = echoedConversationId(request) ?? props.mcpConversationId
                }
                let itemState: ResolvedState | undefined
                try {
                    itemState = TRACKED_METHODS.has(request.method)
                        ? await this.stateResolver.resolve(itemProps, lookups)
                        : undefined
                } catch (error) {
                    if (mapErrorToAuthResponse(error)) {
                        throw error
                    }
                    console.error('[McpDispatcher] Internal error:', error)
                    return jsonRpcMethodError(request.id, ErrorCode.InternalError, 'Internal error')
                }
                return this.dispatch(
                    request,
                    itemProps,
                    itemState,
                    getPublicUrl(req).origin,
                    Boolean(itemProps.mcpSessionId || itemProps.mcpConversationId)
                )
            })
        )
        return new Response(JSON.stringify(results), { status: 200, headers })
    }

    private async dispatch(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState | undefined,
        requestOrigin: string,
        carriedContextHandle: boolean,
        onLegacyElicitation?: (request: JSONRPCRequest) => void
    ): Promise<JsonRpcResponse> {
        const { id, method, params } = request

        // Version and header validation for modern requests happens in
        // `handleRequest` before dispatch; here `_meta` only picks the dialect.
        const protocolMeta = parseRequestProtocolMeta(params)
        const stateless = protocolMeta.protocolVersion === STATELESS_PROTOCOL_VERSION

        try {
            const result = await this.dispatchMethod(
                method,
                params,
                props,
                state,
                stateless,
                id,
                requestOrigin,
                carriedContextHandle,
                onLegacyElicitation
            )
            if (result === METHOD_NOT_FOUND) {
                return jsonRpcMethodError(id, ErrorCode.MethodNotFound, 'Method not found')
            }
            return jsonRpcResult(id, stateless ? this.decorateStatelessResult(method, result) : result)
        } catch (error) {
            if (error instanceof InterviewRequestError) {
                return jsonRpcMethodError(id, ErrorCode.InvalidParams, error.message)
            }
            console.error('[McpDispatcher] Internal error:', error)
            return jsonRpcMethodError(id, ErrorCode.InternalError, 'Internal error')
        }
    }

    /** Returns the raw result for the method, or `METHOD_NOT_FOUND` for unknown methods. */
    private async dispatchMethod(
        method: string,
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState | undefined,
        stateless: boolean,
        requestId: string | number,
        requestOrigin: string,
        carriedContextHandle: boolean,
        onLegacyElicitation?: (request: JSONRPCRequest) => void
    ): Promise<unknown> {
        // SEP-2575 removed `initialize` and `ping` from the modern dialect.
        if (stateless && (method === Method.Initialize || method === Method.Ping)) {
            return METHOD_NOT_FOUND
        }
        switch (method) {
            case Method.Initialize:
                return await this.handleInitialize(params, props, state!)
            case Method.Discover:
                return await this.handleDiscover(props, state!)
            case Method.ToolsList:
                return await this.toolExecutor.handleToolsList(state!)
            case Method.ToolsCall:
                return await this.toolExecutor.handleToolCall(
                    params,
                    state!,
                    params
                        ? {
                              carriedContextHandle,
                              resolveConversation: (conversationId) => {
                                  props.mcpConversationId = conversationId
                                  return this.stateResolver.resolve(props, state!.reqCtx.lookups)
                              },
                              beforeExecute: (callState) =>
                                  this.interviewRecruitment.beforeToolCall(
                                      params,
                                      callState,
                                      props.userHash,
                                      requestOrigin,
                                      onLegacyElicitation ? 'legacy' : 'stateless',
                                      !!onLegacyElicitation
                                  ),
                              afterExecute: async (callState, result) => {
                                  if (onLegacyElicitation) {
                                      const request = await this.interviewRecruitment.afterLegacyToolCall(
                                          params,
                                          callState,
                                          result,
                                          requestId,
                                          props.userHash,
                                          requestOrigin
                                      )
                                      if (request) {
                                          onLegacyElicitation(request)
                                      }
                                  } else {
                                      await this.interviewRecruitment.afterToolCall(
                                          params,
                                          callState,
                                          result,
                                          requestId
                                      )
                                  }
                              },
                          }
                        : undefined
                )
            case Method.ResourcesList:
                return this.resourceCatalog.getResourcesList()
            case Method.ResourcesRead:
                return await this.resourceCatalog.readResource(params)
            case Method.PromptsList:
                return this.resourceCatalog.getPromptsList()
            case Method.PromptsGet:
                return this.resourceCatalog.getPrompt(params)
            case Method.Ping:
                return {}
            default:
                return METHOD_NOT_FOUND
        }
    }

    // 2026-07-28 results carry `resultType`, the server's identity in `_meta`,
    // and (for CacheableResult methods) client-cache freshness hints. Legacy
    // requests keep the exact pre-existing wire shape.
    private decorateStatelessResult(method: string, result: unknown): unknown {
        const base = result && typeof result === 'object' ? (result as Record<string, unknown>) : {}
        const existingMeta =
            base._meta && typeof base._meta === 'object' ? (base._meta as Record<string, unknown>) : undefined
        return {
            ...base,
            resultType: base.resultType === 'input_required' ? 'input_required' : 'complete',
            ...(CACHEABLE_METHODS.has(method)
                ? { ttlMs: CACHEABLE_RESULT_TTL_MS, cacheScope: 'private' as const }
                : {}),
            _meta: {
                ...existingMeta,
                [META_SERVER_INFO]: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            },
        }
    }

    private async handleInitialize(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<InitializeResult> {
        // A client that sends `initialize` is speaking the legacy dialect, so
        // negotiation stays within the SDK's pre-stateless version list — a
        // 2026-07-28-capable client falling back here gets the newest legacy
        // version, matching the spec's fallback-negotiation behavior.
        const requestedVersion = (params?.protocolVersion as string) ?? LATEST_PROTOCOL_VERSION
        const protocolVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
            ? requestedVersion
            : LATEST_PROTOCOL_VERSION

        const instructions = await this.recordDiscoveryRequest('initialize', props, state)

        return {
            protocolVersion,
            capabilities: SERVER_CAPABILITIES,
            serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            ...(instructions ? { instructions } : {}),
        }
    }

    // `server/discover` is the stateless counterpart of `initialize`: same
    // capability/instruction payload, but no version negotiation (each request
    // self-describes) and no session minting. Server identity rides in the
    // result `_meta` via `decorateStatelessResult`.
    private async handleDiscover(props: RequestProperties, state: ResolvedState): Promise<Record<string, unknown>> {
        const instructions = await this.recordDiscoveryRequest('discover', props, state)
        return {
            // Modern versions only: legacy support is reachable solely through
            // the `initialize` fallback, and legacy clients never call discover.
            // Advertising legacy versions here would invite modern clients to
            // select one via `_meta`, which we reject.
            supportedVersions: [...MODERN_PROTOCOL_VERSIONS],
            capabilities: SERVER_CAPABILITIES,
            serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            ...(instructions ? { instructions } : {}),
        }
    }

    /**
     * Shared side effects of the two discovery entry points (`initialize` and
     * `server/discover`): context-mill revalidation, init metrics, and the
     * `$mcp_initialize` analytics event. Returns the per-user instructions.
     */
    private async recordDiscoveryRequest(
        source: 'initialize' | 'discover',
        props: RequestProperties,
        state: ResolvedState
    ): Promise<string | undefined> {
        try {
            await this.resourceCatalog.revalidateContextMillResources(source)
            const instructions = this.instructionsBuilder.build(state)

            initDurationSeconds.observe(props.requestStartTime ? (Date.now() - props.requestStartTime) / 1000 : 0)
            initTotal.inc({ status: 'success' })

            void trackInitEvent(state)

            return instructions
        } catch (error) {
            initTotal.inc({ status: mapErrorToAuthResponse(error) ? 'auth_error' : 'error' })
            throw error
        }
    }
}
