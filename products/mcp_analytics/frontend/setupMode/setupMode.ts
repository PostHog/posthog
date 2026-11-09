import type { MCPOnboardingState } from '../mcpAnalyticsOnboardingLogic'

export type MCPSetupStep = 'connect' | 'first-call' | 'useful'

export const MCP_SETUP_STEPS: MCPSetupStep[] = ['connect', 'first-call', 'useful']

// pinned: URL params, bookmarks and shared links depend on them
export const SETUP_PARAM = 'setup'
export const SETUP_STEP_PARAM = 'setup_step'
export const SETUP_OPEN = 'open'

export type MCPSetupTrigger = 'start_button' | 'scene_button' | 'url'

export type MCPSetupExitReason = 'back' | 'escape' | 'finished' | 'ask_ai' | 'navigated'

export function isSetupOpen(searchParams: Record<string, unknown>): boolean {
    return searchParams[SETUP_PARAM] === SETUP_OPEN
}

/**
 * Only `useful` is stored in the URL. The other two steps follow the data: no tool call yet means
 * the user is still connecting, and the first call moves them on by itself.
 */
export function setupStepFor({
    hasToolCall,
    requestedStep,
}: {
    hasToolCall: boolean
    requestedStep: string | null
}): MCPSetupStep {
    if (!hasToolCall) {
        return 'connect'
    }
    return requestedStep === 'useful' ? 'useful' : 'first-call'
}

export type MCPConnectState = { kind: 'waiting' } | { kind: 'connected' }

export function connectStateFor(onboardingState: MCPOnboardingState | null): MCPConnectState {
    return onboardingState === 'connected-no-calls' || onboardingState === 'onboarded'
        ? { kind: 'connected' }
        : { kind: 'waiting' }
}

/** The tools a connected server offers, and which of them agents have called. */
export interface MCPServerTools {
    /** From the latest `tools/list` response, in the server's order. `null` until a client lists tools. */
    listed: string[] | null
    called: string[]
}

function toolNames(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return []
    }
    return [...new Set(value.filter((name): name is string => typeof name === 'string' && name !== ''))]
}

// The query decodes `$mcp_listed_tool_names` into an array. ClickHouse fills an empty one when no
// listing matched, and the SDKs never send an empty listing, so empty means none yet.
function listedToolNames(value: unknown): string[] | null {
    const names = toolNames(value)
    return names.length > 0 ? names : null
}

/**
 * Reads the `[[listed, server], [server, tool][]]` row of the server tools query. A project can run
 * several servers, so only calls to the server that sent the listing count against it.
 */
export function serverToolsFrom(row: readonly unknown[] | undefined): MCPServerTools {
    const listing = Array.isArray(row?.[0]) ? (row[0] as unknown[]) : []
    const server = typeof listing[1] === 'string' && listing[1] !== '' ? listing[1] : null
    const calls = Array.isArray(row?.[1]) ? (row[1] as unknown[]) : []
    const called = calls
        .filter((pair): pair is [unknown, unknown] => Array.isArray(pair))
        .filter(([callServer]) => server === null || callServer === server)
        .map(([, tool]) => tool)
    // ClickHouse returns the calls in no fixed order, so sort them to keep rows still between polls.
    return { listed: listedToolNames(listing[0]), called: toolNames(called).sort() }
}
