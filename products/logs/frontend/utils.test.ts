import { getSessionIdFromLogAttributes, isDistinctIdKey, isSessionIdKey } from './utils'

describe('logs utils', () => {
    describe.each([
        // Exact matches
        ['distinct.id', true],
        ['distinct_id', true],
        ['distinctId', true],
        ['distinctID', true],
        ['posthogDistinctId', true],
        ['posthogDistinctID', true],
        ['posthog_distinct_id', true],
        ['posthog.distinct.id', true],
        ['posthog.distinct_id', true],
        // Dotted paths
        ['foo.distinct_id', true],
        ['foo.bar.posthogDistinctId', true],
        ['foo.bar.posthog_distinct_id', true],
        ['foo.bar.distinct_id', true],
        ['foo.bar.distinct.id', true],
        ['resource.attributes.distinct_id', true],
        // Non-matches
        ['not_distinct_id_at_all', false],
        ['distinct_id.something', false],
        ['xdistinct_id', false],
        ['', false],
    ])('isDistinctIdKey(%s)', (key, expected) => {
        it(`returns ${expected}`, () => {
            expect(isDistinctIdKey(key)).toBe(expected)
        })
    })

    describe.each([
        // Exact matches
        ['session.id', true],
        ['session_id', true],
        ['sessionId', true],
        ['sessionID', true],
        ['$session_id', true],
        ['posthogSessionId', true],
        ['posthogSessionID', true],
        ['posthog_session_id', true],
        ['posthog.session.id', true],
        ['posthog.session_id', true],
        // Dotted paths
        ['foo.session_id', true],
        ['foo.bar.posthogSessionId', true],
        ['foo.bar.posthog_session_id', true],
        ['foo.bar.session_id', true],
        ['foo.bar.session.id', true],
        ['resource.attributes.$session_id', true],
        // Non-matches
        ['not_session_id_at_all', false],
        ['session_id.something', false],
        ['xsession_id', false],
        ['', false],
    ])('isSessionIdKey(%s)', (key, expected) => {
        it(`returns ${expected}`, () => {
            expect(isSessionIdKey(key)).toBe(expected)
        })
    })

    describe.each([
        ['from attributes', { session_id: 'abc123' }, undefined, 'abc123'],
        ['from resource_attributes', undefined, { session_id: 'xyz789' }, 'xyz789'],
        ['attributes takes precedence', { session_id: 'from-attr' }, { session_id: 'from-resource' }, 'from-attr'],
        ['nested key in attributes', { 'foo.session_id': 'nested' }, undefined, 'nested'],
        ['$session_id variant', { $session_id: 'dollar-sign' }, undefined, 'dollar-sign'],
        ['no session id', { other_key: 'value' }, { another_key: 'value' }, null],
        ['empty objects', {}, {}, null],
        ['undefined inputs', undefined, undefined, null],
        ['ignores falsy values', { session_id: '' }, { session_id: 'fallback' }, 'fallback'],
        ['ignores null values', { session_id: null }, { session_id: 'fallback' }, 'fallback'],
        ['converts number to string', { session_id: 12345 }, undefined, '12345'],
    ])('getSessionIdFromLogAttributes - %s', (_, attributes, resourceAttributes, expected) => {
        it(`returns ${expected}`, () => {
            expect(
                getSessionIdFromLogAttributes(
                    attributes as Record<string, unknown> | undefined,
                    resourceAttributes as Record<string, unknown> | undefined
                )
            ).toBe(expected)
        })
    })
})
