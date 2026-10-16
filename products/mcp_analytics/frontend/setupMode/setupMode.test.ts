import { connectStateFor, parseSetupPath, setupStepFor } from './setupMode'

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

    it.each([
        { onboardingState: null, expected: 'waiting' },
        { onboardingState: 'not-instrumented', expected: 'waiting' },
        { onboardingState: 'connected-no-calls', expected: 'connected' },
        { onboardingState: 'onboarded', expected: 'connected' },
    ] as const)('onboarding state $onboardingState resolves to $expected', ({ onboardingState, expected }) => {
        expect(connectStateFor(onboardingState)).toEqual({ kind: expected })
    })

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
