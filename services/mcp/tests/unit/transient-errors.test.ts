import { describe, expect, test } from 'vitest'

import { isTransientShutdownError } from '@/lib/transient-errors'

describe('isTransientShutdownError', () => {
    test.each([
        ['Error: destroyed', true],
        ['destroyed', true],
        ['DESTROYED', true],
        [
            'Error in MCP:streamable-http:abc123 webSocketClose: Error: Durable Object reset because its code was updated.',
            true,
        ],
        ['Error in MCP:streamable-http:abc webSocketError: connection closed', true],
        ['Durable Object reset because its code was updated.', true],
        ['INVALID_API_KEY', false],
        ['Cannot read properties of null', false],
        ['', false],
        ['Failed to get user', false],
    ])('%s -> %s', (message, expected) => {
        expect(isTransientShutdownError(new Error(message))).toBe(expected)
    })

    test('returns false for null/undefined', () => {
        expect(isTransientShutdownError(null)).toBe(false)
        expect(isTransientShutdownError(undefined)).toBe(false)
    })

    test('matches plain string errors', () => {
        expect(isTransientShutdownError('destroyed')).toBe(true)
        expect(isTransientShutdownError('something else')).toBe(false)
    })
})
