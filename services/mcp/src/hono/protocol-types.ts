import type { MCPClientProfile } from '@/lib/client-detection'
import type { RequestProperties } from '@/lib/request-properties'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'
import type { McpMode } from '@/lib/utils'

import type { RequestContext } from './request-context'

// ─── Pre-built response types ───

export interface PreBuiltToolEntry {
    name: string
    title: string
    description: string
    inputSchema: Record<string, unknown>
    annotations?: Record<string, unknown>
    _meta?: Record<string, unknown>
}

export interface PreBuiltResource {
    name: string
    uri: string
    mimeType: string
    description: string
}

export interface PreBuiltPrompt {
    name: string
    title: string
    description: string
}

export interface ResourceReadEntry {
    uri: string
    mimeType: string
    text: string
    _meta?: Record<string, unknown>
}

export interface PromptGetEntry {
    messages: Array<{ role: string; content: { type: string; text: string } }>
}

// ─── JSON-RPC types ───

export interface JsonRpcRequest {
    jsonrpc: '2.0'
    id: number | string
    method: string
    params?: Record<string, unknown>
}

interface JsonRpcNotification {
    jsonrpc: '2.0'
    method: string
    params?: Record<string, unknown>
}

export type JsonRpcMessage = JsonRpcRequest | JsonRpcNotification

export function isRequest(msg: JsonRpcMessage): msg is JsonRpcRequest {
    return typeof msg === 'object' && msg !== null && 'id' in msg && typeof (msg as any).method === 'string'
}

const TRACKED_METHODS = new Set(['initialize', 'tools/list', 'tools/call'])

export function isTrackedMethod(method: string): boolean {
    return TRACKED_METHODS.has(method)
}

export function jsonRpcError(id: unknown, code: number, message: string): Response {
    return new Response(
        JSON.stringify({
            jsonrpc: '2.0',
            id: id ?? null,
            error: { code, message },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
}

// ─── Per-request resolved state ───

export interface ResolvedState {
    reqCtx: RequestContext
    context: Context
    version: number
    useSingleExec: boolean
    toolFeatureFlags: Record<string, boolean> | undefined
    apiKeyScopes: string[]
    clientProfile: MCPClientProfile
    allTools: Tool<ZodObjectAny>[]
    distinctId: string
}

// ─── Method handler callbacks (used by AnalyticsBridge) ───

export interface MethodHandlerCallbacks {
    handleInitialize(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<unknown>
    handleToolsList(state: ResolvedState, props: RequestProperties): Promise<{ tools: PreBuiltToolEntry[] }>
    handleToolCall(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<unknown>
}

// ─── Pure functions ───

export function resolveModeAndVersion(args: {
    mode: McpMode | undefined
    singleExecFlagOn: boolean
    clientProfile: MCPClientProfile
    flagVersion: number | undefined
    clientVersion: number | undefined
}): { useSingleExec: boolean; version: number } {
    const { mode, singleExecFlagOn, clientProfile, flagVersion, clientVersion } = args
    const useSingleExec =
        mode === 'cli' ||
        (mode !== 'tools' &&
            singleExecFlagOn &&
            (clientProfile.isCodingAgent() ||
                clientProfile.isPostHogCodeConsumer() ||
                clientProfile.isVibeCodingClient()))
    const version = useSingleExec ? 2 : (flagVersion ?? clientVersion ?? 1)
    return { useSingleExec, version }
}
