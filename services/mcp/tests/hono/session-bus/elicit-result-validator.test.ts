import { describe, expect, it } from 'vitest'

import { validateElicitResult } from '@/hono/session-bus/elicit-result-validator'
import { ElicitationNotSupportedError, SessionBusUnhealthyError } from '@/hono/session-bus/errors'

describe('validateElicitResult', () => {
    it('accepts a well-formed accept result', () => {
        expect(validateElicitResult({ action: 'accept', content: { confirmed: true } })).toEqual({
            action: 'accept',
            content: { confirmed: true },
        })
    })

    it('accepts decline and cancel without content', () => {
        expect(validateElicitResult({ action: 'decline' })).toEqual({ action: 'decline' })
        expect(validateElicitResult({ action: 'cancel' })).toEqual({ action: 'cancel' })
    })

    it('throws ElicitationNotSupportedError for a JSON-RPC error envelope (-32601)', () => {
        let caught: unknown
        try {
            validateElicitResult({ error: { code: -32601, message: 'Method not found' } })
        } catch (e) {
            caught = e
        }
        expect(caught).toBeInstanceOf(ElicitationNotSupportedError)
        const err = caught as ElicitationNotSupportedError
        expect(err.code).toBe(-32601)
        expect(err.message).toContain('Method not found')
    })

    it('throws ElicitationNotSupportedError for an unsupported-mode error (-32602)', () => {
        let caught: unknown
        try {
            validateElicitResult({
                error: { code: -32602, message: 'Client does not support URL-mode elicitation requests' },
            })
        } catch (e) {
            caught = e
        }
        expect(caught).toBeInstanceOf(ElicitationNotSupportedError)
        expect((caught as ElicitationNotSupportedError).code).toBe(-32602)
    })

    it('throws SessionBusUnhealthyError for a malformed payload (no action, no error)', () => {
        expect(() => validateElicitResult({ not: 'a valid ElicitResult' })).toThrow(SessionBusUnhealthyError)
    })

    it('throws SessionBusUnhealthyError for an action with an invalid value', () => {
        expect(() => validateElicitResult({ action: 'maybe' })).toThrow(SessionBusUnhealthyError)
    })

    it('treats an error object without numeric code as malformed (unhealthy, not not-supported)', () => {
        // Don't misclassify garbage as a polite "client doesn't support this".
        // It's a malformed payload — fail closed under the bus health bucket.
        expect(() => validateElicitResult({ error: { code: 'oops', message: 'nope' } })).toThrow(
            SessionBusUnhealthyError
        )
    })

    it('treats a null payload as malformed', () => {
        expect(() => validateElicitResult(null)).toThrow(SessionBusUnhealthyError)
    })
})
