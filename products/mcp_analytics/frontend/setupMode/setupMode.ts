import type { MCPOnboardingState } from '../mcpAnalyticsOnboardingLogic'

export type MCPSetupStep = 'connect' | 'first-call' | 'useful'

export const MCP_SETUP_STEPS: MCPSetupStep[] = ['connect', 'first-call', 'useful']

// pinned: URL params, bookmarks and shared links depend on them
export const SETUP_PARAM = 'setup'
export const SETUP_STEP_PARAM = 'setup_step'
export const SETUP_OPEN = 'open'

export type MCPSetupTrigger = 'start_button' | 'url'

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
