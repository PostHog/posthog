import type { MCPOnboardingState } from '../mcpAnalyticsOnboardingLogic'

/** The button that opened setup mode. Pinned: the `setup` URL param carries these values. */
export type MCPSetupPath = 'wizard' | 'agent'

export type MCPSetupStep = 'connect' | 'first-call' | 'useful'

export const MCP_SETUP_STEPS: MCPSetupStep[] = ['connect', 'first-call', 'useful']

// pinned: URL params, bookmarks and shared links depend on them
export const SETUP_PARAM = 'setup'
export const SETUP_STEP_PARAM = 'setup_step'

export type MCPSetupTrigger = 'wizard_copy' | 'agent_copy' | 'url'

export type MCPSetupExitReason = 'back' | 'escape' | 'finished'

export function parseSetupPath(value: unknown): MCPSetupPath | null {
    return value === 'wizard' || value === 'agent' ? value : null
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
