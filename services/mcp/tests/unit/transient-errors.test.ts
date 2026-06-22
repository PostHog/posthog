import { describe, expect, it } from 'vitest'

import { isTransientUpstreamError, PostHogApiError, PostHogRateLimitError, wrapError } from '@/lib/errors'

function apiError(status: number): PostHogApiError {
    return new PostHogApiError({
        status,
        statusText: 'error',
        body: 'upstream request timeout',
        url: '/api/projects/246647/',
        method: 'GET',
    })
}

function networkError(opts: { name?: string; code?: string }): Error {
    const err = new Error('network failure') as Error & { code?: string }
    if (opts.name) {
        err.name = opts.name
    }
    if (opts.code) {
        err.code = opts.code
    }
    return err
}

describe('isTransientUpstreamError', () => {
    it.each([502, 503, 504])('treats a %i gateway error as transient', (status) => {
        expect(isTransientUpstreamError(apiError(status))).toBe(true)
    })

    it.each([400, 401, 403, 404, 422, 500])('treats a %i error as non-transient', (status) => {
        expect(isTransientUpstreamError(apiError(status))).toBe(false)
    })

    it.each([
        'UND_ERR_CONNECT_TIMEOUT',
        'UND_ERR_HEADERS_TIMEOUT',
        'UND_ERR_BODY_TIMEOUT',
        'UND_ERR_SOCKET',
        'ETIMEDOUT',
        'ECONNRESET',
        'ECONNREFUSED',
        'EAI_AGAIN',
    ])('treats network code %s as transient', (code) => {
        expect(isTransientUpstreamError(networkError({ code }))).toBe(true)
    })

    it.each(['AbortError', 'TimeoutError'])('treats error name %s as transient', (name) => {
        expect(isTransientUpstreamError(networkError({ name }))).toBe(true)
    })

    it('unwraps a transient error wrapped via cause', () => {
        const wrapped = wrapError('Failed to get project: upstream request timeout', apiError(504))
        expect(isTransientUpstreamError(wrapped)).toBe(true)
    })

    it('unwraps a transient network error nested as a fetch TypeError cause', () => {
        const cause = networkError({ code: 'UND_ERR_CONNECT_TIMEOUT' })
        const typeError = new TypeError('fetch failed') as TypeError & { cause?: unknown }
        typeError.cause = cause
        expect(isTransientUpstreamError(typeError)).toBe(true)
    })

    it('does not treat a rate-limit (429) as transient — it is surfaced, not retried here', () => {
        const rateLimit = new PostHogRateLimitError({
            body: 'slow down',
            url: '/api/projects/246647/',
            method: 'GET',
            retryAfterSeconds: 5,
        })
        expect(isTransientUpstreamError(rateLimit)).toBe(false)
    })

    it.each([undefined, null, 'a string', new Error('plain error'), {}])(
        'treats unrelated value %s as non-transient',
        (value) => {
            expect(isTransientUpstreamError(value)).toBe(false)
        }
    )

    it('does not loop forever on a self-referential cause chain', () => {
        const err = new Error('cyclic') as Error & { cause?: unknown }
        err.cause = err
        expect(isTransientUpstreamError(err)).toBe(false)
    })
})
