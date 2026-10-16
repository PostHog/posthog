import type { InstallationStep } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

import type { MCPOnboardingState } from '../mcpAnalyticsOnboardingLogic'
import {
    type MCPConnectState,
    type MCPSetupPath,
    type MCPWizardRun,
    connectStateFor,
    parseSetupPath,
    setupStepFor,
} from './setupMode'

const TASKS: InstallationStep[] = [
    { id: 'a', label: 'Find the MCP server entry point', status: 'completed', detail: null },
    { id: 'b', label: 'Install @posthog/mcp', status: 'in_progress', detail: null },
]
const RUN: MCPWizardRun = { tasks: TASKS, pendingInput: null, error: null }

describe('setupMode', () => {
    it.each([
        { hasToolCall: false, requestedStep: null, expected: 'connect' },
        { hasToolCall: false, requestedStep: 'useful', expected: 'connect' },
        { hasToolCall: true, requestedStep: null, expected: 'first-call' },
        { hasToolCall: true, requestedStep: 'connect', expected: 'first-call' },
        { hasToolCall: true, requestedStep: 'useful', expected: 'useful' },
    ] as const)(
        'tool call $hasToolCall and requested step $requestedStep resolve to $expected',
        ({ hasToolCall, requestedStep, expected }) => {
            expect(setupStepFor({ hasToolCall, requestedStep })).toBe(expected)
        }
    )

    const connectCases: {
        path: MCPSetupPath
        onboardingState: MCPOnboardingState | null
        wizardRun: MCPWizardRun | null
        expected: MCPConnectState
    }[] = [
        { path: 'wizard', onboardingState: 'not-instrumented', wizardRun: null, expected: { kind: 'waiting' } },
        {
            path: 'wizard',
            onboardingState: 'not-instrumented',
            wizardRun: RUN,
            expected: { kind: 'wizard-running', run: RUN },
        },
        { path: 'wizard', onboardingState: 'connected-no-calls', wizardRun: RUN, expected: { kind: 'connected' } },
        { path: 'agent', onboardingState: 'not-instrumented', wizardRun: RUN, expected: { kind: 'waiting' } },
        { path: 'agent', onboardingState: 'connected-no-calls', wizardRun: null, expected: { kind: 'connected' } },
        { path: 'agent', onboardingState: null, wizardRun: null, expected: { kind: 'waiting' } },
    ]

    it.each(connectCases.map((row) => ({ ...row, hasRun: row.wizardRun !== null })))(
        '$path path, $onboardingState, with a wizard run: $hasRun, resolves to $expected.kind',
        ({ path, onboardingState, wizardRun, expected }) => {
            expect(connectStateFor({ path, onboardingState, wizardRun })).toEqual(expected)
        }
    )

    it.each([
        { value: 'wizard', expected: 'wizard' },
        { value: 'agent', expected: 'agent' },
        { value: 'manual', expected: null },
        { value: undefined, expected: null },
        { value: 1, expected: null },
    ])('parses the setup param $value as $expected', ({ value, expected }) => {
        expect(parseSetupPath(value)).toBe(expected)
    })
})
