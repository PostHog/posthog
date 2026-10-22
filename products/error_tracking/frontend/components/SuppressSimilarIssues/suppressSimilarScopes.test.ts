import {
    SuppressedIssueSnapshot,
    buildScopeOptions,
    generalizeExceptionMessage,
    recommendedScope,
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
            const messageFilter = similar.filters.values.find((filter) => filter.key === '$exception_values')!
            const regex = new RegExp(messageFilter.value as string)
            expect(messages.every((message) => regex.test(message))).toBe(true)
            expect(regex.test(unmatched)).toBe(false)
            expect(similar.messages).toHaveLength(expectedPatternCount)
        }
    )
})
