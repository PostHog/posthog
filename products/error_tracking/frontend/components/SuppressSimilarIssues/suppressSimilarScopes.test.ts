import { PropertyOperator } from '~/types'

import {
    SuppressedIssueSnapshot,
    buildScopeOptions,
    generalizeExceptionMessage,
    recommendedScope,
    snapshotFromLatestEvent,
} from './suppressSimilarScopes'

function snapshot(overrides: Partial<SuppressedIssueSnapshot>): SuppressedIssueSnapshot {
    return { id: 'issue-1', exceptionType: 'TypeError', exceptionMessage: null, ...overrides }
}

describe('suppressSimilarScopes', () => {
    test.each([
        {
            message: 'Request failed with status code 503',
            similar: 'Request failed with status code 404',
            different: 'Request failed with status code unknown',
        },
        {
            message: 'User 6f1c2a3e-1b2c-4d5e-8f90-123456789abc not found (attempt 2.5)',
            similar: 'User 0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d not found (attempt 10)',
            different: 'User admin not found (attempt 2)',
        },
        {
            message: 'Chunk a1b2c3d4e5f60718 failed to load from /static/[id].js?v=1',
            similar: 'Chunk ffee00112233aabb failed to load from /static/[id].js?v=42',
            different: 'Chunk a1b2c3d4e5f60718 failed to load from /static/xid.js?v=1',
        },
        {
            message: 'Address 0XDEADBEEF failed',
            similar: 'Address 0x1f3a failed',
            different: 'Address main failed',
        },
    ])('generalized pattern for "$message" matches similar messages only', ({ message, similar, different }) => {
        const generalized = generalizeExceptionMessage(message)
        expect(generalized).not.toBeNull()
        const regex = new RegExp(`^${generalized!.regex}$`)
        expect(regex.test(message)).toBe(true)
        expect(regex.test(similar)).toBe(true)
        expect(regex.test(different)).toBe(false)
    })

    test.each(["Cannot read properties of undefined (reading 'map')", 'utf8 decoding failed in base64 payload'])(
        'leaves "%s" without variable parts ungeneralized',
        (message) => {
            expect(generalizeExceptionMessage(message)).toBeNull()
        }
    )

    test.each([
        {
            name: 'a variable message recommends similar messages',
            snapshots: [snapshot({ exceptionMessage: 'Timeout after 3000ms' })],
            recommended: 'similar',
            unavailable: [],
        },
        {
            name: 'a fixed message recommends the exact message',
            snapshots: [snapshot({ exceptionMessage: 'Network error' })],
            recommended: 'exact',
            unavailable: ['similar'],
        },
        {
            name: 'no message offers nothing',
            snapshots: [snapshot({ exceptionMessage: null })],
            recommended: null,
            unavailable: ['exact', 'similar'],
        },
    ])('scopes: $name', ({ snapshots, recommended, unavailable }) => {
        const options = buildScopeOptions(snapshots)
        expect(recommendedScope(options)).toEqual(recommended)
        expect(options.filter((option) => option.unavailableReason).map((option) => option.key)).toEqual(unavailable)
    })

    test.each([
        {
            name: 'different messages',
            messages: ['Timeout after 3000ms', 'Network error'],
            expectedPatternCount: 2,
            unmatched: 'Network error 2',
        },
        {
            name: 'messages that differ only by a number',
            messages: ['Loading chunk 482 failed.', 'Loading chunk 917 failed.'],
            expectedPatternCount: 1,
            unmatched: 'Loading chunk main failed.',
        },
    ])(
        'combines several issues into one pattern that matches each of them: $name',
        ({ messages, expectedPatternCount, unmatched }) => {
            const similar = buildScopeOptions(
                messages.map((exceptionMessage, index) => snapshot({ id: `issue-${index}`, exceptionMessage }))
            ).find((option) => option.key === 'similar')!
            expect(similar.rules).toHaveLength(1)
            const messageFilter = similar.rules[0].values.find((filter) => filter.key === '$exception_values')!
            const regex = new RegExp(messageFilter.value as string)
            expect(messages.every((message) => regex.test(message))).toBe(true)
            expect(regex.test(unmatched)).toBe(false)
            expect(similar.messages).toHaveLength(expectedPatternCount)
        }
    )

    it('keeps each exception type with its own messages when several types are suppressed together', () => {
        const similar = buildScopeOptions([
            snapshot({ id: 'type-error', exceptionType: 'TypeError', exceptionMessage: 'alpha 1' }),
            snapshot({ id: 'range-error', exceptionType: 'RangeError', exceptionMessage: 'beta 1' }),
        ]).find((option) => option.key === 'similar')!
        const rules = similar.rules.map((rule) => ({
            type: rule.values.find((filter) => filter.key === '$exception_types')!.value,
            message: new RegExp(rule.values.find((filter) => filter.key === '$exception_values')!.value as string),
        }))
        expect(rules.map((rule) => rule.type)).toEqual([['TypeError'], ['RangeError']])
        expect(rules.map((rule) => [rule.message.test('alpha 2'), rule.message.test('beta 2')])).toEqual([
            [true, false],
            [false, true],
        ])
    })

    test.each([
        { name: 'a JSON array, as HogQL returns it', raw: '["Error","TypeError"]', expected: 'Error' },
        { name: 'a plain string', raw: 'Error', expected: 'Error' },
        { name: 'no value', raw: null, expected: null },
    ])('reads the outermost exception from $name', ({ raw, expected }) => {
        expect(snapshotFromLatestEvent(['issue-1', raw, raw])).toEqual({
            id: 'issue-1',
            exceptionType: expected,
            exceptionMessage: expected,
        })
    })

    it('reads a dotted run of numbers as one placeholder', () => {
        const generalized = generalizeExceptionMessage('Upgrade to 1.2.3.4 failed')!
        expect(generalized.segments.filter((segment) => segment.kind === 'number')).toEqual([
            { kind: 'number', text: '1.2.3.4' },
        ])
        expect(new RegExp(`^${generalized.regex}$`).test('Upgrade to 10.0 failed')).toBe(true)
    })

    test.each([
        {
            name: 'many messages split across rules',
            messages: Array.from(
                { length: 40 },
                (_, index) => `Worker ${'w'.repeat(30)}${index} stopped after 5 retries`
            ),
            exactRules: 0,
        },
        {
            name: 'a message too long for any pattern falls back to an exact match',
            messages: [`Payload ${'x'.repeat(1100)} rejected with code 413`],
            exactRules: 1,
        },
    ])('keeps every similar pattern within the regex cache limit: $name', ({ messages, exactRules }) => {
        const similar = buildScopeOptions(
            messages.map((exceptionMessage, index) => snapshot({ id: `issue-${index}`, exceptionMessage }))
        ).find((option) => option.key === 'similar')!
        const messageFilters = similar.rules.map(
            (rule) => rule.values.find((filter) => filter.key === '$exception_values')!
        )
        const regexes = messageFilters
            .filter((filter) => filter.operator === PropertyOperator.Regex)
            .map((filter) => String(filter.value))
        expect(regexes.every((regex) => new TextEncoder().encode(regex).length <= 1024)).toBe(true)
        expect(messageFilters.filter((filter) => filter.operator === PropertyOperator.Exact)).toHaveLength(exactRules)
        expect(
            messages.every(
                (message) =>
                    regexes.some((regex) => new RegExp(regex).test(message)) ||
                    messageFilters.some(
                        (filter) => filter.operator === PropertyOperator.Exact && filter.value.includes(message)
                    )
            )
        ).toBe(true)
    })
})
