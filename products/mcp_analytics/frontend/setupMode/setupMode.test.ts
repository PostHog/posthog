import { connectStateFor, isSetupOpen, serverToolsFrom, setupStepFor } from './setupMode'

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
        { value: 'open', expected: true },
        { value: 'agent', expected: false },
        { value: undefined, expected: false },
    ])('reads the setup param $value as open: $expected', ({ value, expected }) => {
        expect(isSetupOpen({ setup: value })).toBe(expected)
    })

    it.each([
        {
            case: 'a listed and a called tool',
            row: [[['search_docs', 'create_issue'], 'docs'], [['docs', 'search_docs']]],
            expected: { listed: ['search_docs', 'create_issue'], called: ['search_docs'] },
        },
        {
            case: 'calls to another server',
            row: [
                [['search_docs'], 'docs'],
                [
                    ['billing', 'refund'],
                    ['docs', 'search_docs'],
                ],
            ],
            expected: { listed: ['search_docs'], called: ['search_docs'] },
        },
        {
            case: 'a listing without a server name',
            row: [
                [['search_docs', 'refund'], null],
                [
                    ['billing', 'refund'],
                    ['docs', 'search_docs'],
                ],
            ],
            expected: { listed: ['search_docs', 'refund'], called: ['refund', 'search_docs'] },
        },
        {
            case: 'no tools/list yet',
            row: [
                [null, null],
                [
                    ['docs', 'search_docs'],
                    [null, 'create_issue'],
                ],
            ],
            expected: { listed: null, called: ['create_issue', 'search_docs'] },
        },
        {
            case: 'no tools/list as ClickHouse returns it',
            row: [[[], null], [['docs', 'search_docs']]],
            expected: { listed: null, called: ['search_docs'] },
        },
        {
            case: 'a listing that is not a list',
            row: [['search_docs', null], []],
            expected: { listed: null, called: [] },
        },
        {
            case: 'blank and repeated tool names',
            row: [
                [['a', '', 'a'], null],
                [
                    [null, ''],
                    [null, 'a'],
                ],
            ],
            expected: { listed: ['a'], called: ['a'] },
        },
        { case: 'no row', row: undefined, expected: { listed: null, called: [] } },
    ])('reads the server tools from $case', ({ row, expected }) => {
        expect(serverToolsFrom(row)).toEqual(expected)
    })
})
