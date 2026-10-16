import type {
    InstallationProgress,
    InstallationStep,
    WizardPendingInput,
} from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

import type { MCPOnboardingState } from '../mcpAnalyticsOnboardingLogic'

/** The install route the user committed to. Pinned: the `setup` URL param carries these values. */
export type MCPSetupPath = 'wizard' | 'agent'

export type MCPSetupStep = 'connect' | 'first-call' | 'useful'

export const MCP_SETUP_STEPS: MCPSetupStep[] = ['connect', 'first-call', 'useful']

// pinned: URL params, bookmarks and shared links depend on them
export const SETUP_PARAM = 'setup'
export const SETUP_STEP_PARAM = 'setup_step'

export type MCPSetupTrigger = 'wizard_copy' | 'agent_copy' | 'wizard_detected' | 'url'

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

/** A wizard run for this project that is live right now, as reported from the user's terminal. */
export interface MCPWizardRun {
    tasks: InstallationStep[]
    pendingInput: WizardPendingInput | null
    error: InstallationProgress['error']
}

export type MCPConnectState =
    | { kind: 'waiting' }
    | { kind: 'wizard-running'; run: MCPWizardRun }
    | { kind: 'connected' }

/** The agent path has no progress stream, so it only ever waits and then connects. */
export function connectStateFor({
    path,
    onboardingState,
    wizardRun,
}: {
    path: MCPSetupPath
    onboardingState: MCPOnboardingState | null
    wizardRun: MCPWizardRun | null
}): MCPConnectState {
    if (onboardingState === 'connected-no-calls' || onboardingState === 'onboarded') {
        return { kind: 'connected' }
    }
    if (path === 'wizard' && wizardRun) {
        return { kind: 'wizard-running', run: wizardRun }
    }
    return { kind: 'waiting' }
}
