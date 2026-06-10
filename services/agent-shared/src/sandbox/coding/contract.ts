/**
 * The tier-2 coding-sandbox contract — see
 * docs/agent-platform/plans/agent-sandbox-tiers.md.
 *
 * This is the REAL `@posthog/agent` / `agent-server` contract (validated
 * against the published image), and the shape the supervisor (tier 1) drives
 * it through:
 *   - JWT-authed (`Authorization: Bearer`) JSON-RPC `POST /command`.
 *   - JWT-authed SSE `GET /events` — connecting it initializes the session.
 *   - Events are ACP notifications (`session/update` with a `sessionUpdate`
 *     discriminator) and `_posthog/*` lifecycle frames, plus `connected`.
 *   - Permissions are option-based: a request carries `options[]`, the
 *     response selects an `optionId`.
 *   - `GET /health` for readiness.
 *
 * The Docker pool turns a `CodingLaunchConfig` into the container env + flags;
 * the supervisor parses the raw frames into normalized `CodingEvent`s.
 */

export interface McpServerConfig {
    type: 'http' | 'sse'
    name: string
    url: string
    headers: { name: string; value: string }[]
}

/** Renderer output — spec → harness launch config (§3.1 mapping). */
export interface CodingLaunchConfig {
    /** Bare provider SKU the gateway routes, e.g. `claude-sonnet-4-6`. */
    model: string
    provider?: string
    reasoningEffort?: string
    /** Model gateway base URL (`LLM_GATEWAY_URL`) — our session proxy in prod. */
    modelBaseUrl?: string
    /** Gateway token (`POSTHOG_PERSONAL_API_KEY`). */
    apiKey?: string
    /** PostHog API base (`POSTHOG_API_URL`). */
    apiUrl?: string
    /** PostHog project id (`POSTHOG_PROJECT_ID`). */
    projectId?: number
    systemPrompt?: string
    skills: { id: string; description: string }[]
    mcpServers: McpServerConfig[]
    workspace?: { repo?: string; ref: string }
    limits: { memoryMb?: number; cpuCores?: number; wallSeconds?: number }
    writable: boolean
}

/** Commands the supervisor sends over JSON-RPC `POST /command`. */
export type HarnessCommand =
    | { method: 'user_message'; params: { content: string } }
    | { method: 'cancel'; params?: Record<string, never> }
    | { method: 'close'; params?: Record<string, never> }
    | { method: 'permission_response'; params: { requestId: string; optionId: string; customInput?: string } }

export interface JsonRpcResponse {
    jsonrpc: '2.0'
    id: string | number
    result?: unknown
    error?: { code: number; message: string }
}

/** Raw SSE frame off `GET /events`. */
export type HarnessFrame =
    | { type: 'connected'; run_id: string }
    | {
          type: 'notification'
          notification: { jsonrpc: '2.0'; method: string; params?: unknown; id?: string | number; error?: unknown }
      }
    | {
          type: 'permission_request'
          requestId: string
          options: PermissionOption[]
          toolCall?: { toolCallId?: string; rawInput?: unknown; _meta?: unknown }
      }

/** Normalized event the supervisor produces from parsing frames. */
export type CodingEvent =
    | { kind: 'connected' }
    | { kind: 'run_started' }
    | { kind: 'assistant_text'; text: string }
    | { kind: 'thought'; text: string }
    | { kind: 'tool_call'; toolCallId: string; tool?: string; command?: string; title?: string }
    | { kind: 'permission_request'; requestId: string; options: PermissionOption[]; tool?: string; summary?: string }
    | { kind: 'usage'; inputTokens: number; outputTokens: number; costUsd?: number }
    | { kind: 'turn_complete' }
    | { kind: 'task_complete'; result?: unknown }
    | { kind: 'error'; message: string }
    | { kind: 'log'; level: string; message: string }

export interface PermissionOption {
    optionId: string
    name: string
    kind?: string
}

/** Auth material for one session — public key to the container, token to us. */
export interface CodingSandboxAuth {
    publicKeyPem: string
    token: string
}

/** Stable ids the JWT claims and the agent-server flags must agree on. */
export interface HarnessIds {
    taskId: string
    runId: string
}

export interface CodingAcquireOpts {
    sessionId: string
    teamId: number
    launch: CodingLaunchConfig
    auth: CodingSandboxAuth
    harnessIds: HarnessIds
    sessionTimeoutMs?: number
    /** Host path mounted at the sandbox workspace. `readonly` enforces the tier. */
    workspaceMount?: { hostPath: string; readonly: boolean }
}

export interface EventSubscription {
    close: () => void
}

export interface CodingSandbox {
    readonly sessionId: string
    /** Provider handle for out-of-band reaping — docker container id / Modal sandbox id. */
    readonly providerSandboxId: string
    /** Send a JSON-RPC command to the harness (Bearer-authed). */
    command(cmd: HarnessCommand): Promise<JsonRpcResponse>
    /** Open the SSE event stream (Bearer-authed). Connecting initializes the session. */
    openEvents(onFrame: (frame: HarnessFrame) => void): EventSubscription
    isAlive(): Promise<boolean>
    destroy(): Promise<void>
}

export type CodingSandboxKind = 'docker-coding' | 'modal-coding'

export interface CodingSandboxPool {
    readonly kind: CodingSandboxKind
    acquireForSession(opts: CodingAcquireOpts): Promise<CodingSandbox>
    release(sessionId: string): Promise<void>
}
