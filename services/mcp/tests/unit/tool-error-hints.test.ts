import { describe, expect, it, vi } from 'vitest'

import { handleToolError, PostHogApiError, PostHogValidationError, wrapError } from '@/lib/errors'
import { getToolRecoveryHint } from '@/lib/tool-error-hints'

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException: vi.fn() }),
}))

const LOGS_QUERY_URL = 'https://us.posthog.com/api/projects/2/logs/query/'

describe('getToolRecoveryHint', () => {
    it('returns the narrow-and-retry hint for a 5xx on a logs query endpoint', () => {
        const hint = getToolRecoveryHint({ url: LOGS_QUERY_URL, status: 500 })

        expect(hint).not.toBeUndefined()
        expect(hint).toContain('scans too much data')
        expect(hint).toContain('logs-count')
        expect(hint).toContain('logs-count-ranges')
        expect(hint).toContain('serviceNames')
    })

    it.each([
        'https://us.posthog.com/api/projects/2/logs/count/',
        'https://us.posthog.com/api/projects/2/logs/count-ranges/',
        'https://us.posthog.com/api/projects/2/logs/services/',
        'https://us.posthog.com/api/projects/2/logs/sparkline/',
    ])('also fires for the sibling logs query endpoint %s', (url: string) => {
        expect(getToolRecoveryHint({ url, status: 503 })).not.toBeUndefined()
    })

    it.each([400, 404])('does not fire for %i — those carry an actionable detail already', (status) => {
        expect(getToolRecoveryHint({ url: LOGS_QUERY_URL, status })).toBeUndefined()
    })

    it('does not fire for unrelated endpoints', () => {
        expect(
            getToolRecoveryHint({ url: 'https://us.posthog.com/api/projects/2/insights/', status: 500 })
        ).toBeUndefined()
    })

    it('fires when status is unknown but the URL is a logs query endpoint', () => {
        expect(getToolRecoveryHint({ url: LOGS_QUERY_URL })).not.toBeUndefined()
    })
})

describe('handleToolError recovery hints', () => {
    it('appends the recovery hint to a 5xx logs query failure', () => {
        const error = new PostHogApiError({
            status: 500,
            statusText: 'Internal Server Error',
            body: '{"detail":"timeout"}',
            url: LOGS_QUERY_URL,
            method: 'POST',
        })

        const result = handleToolError(error, 'query-logs')
        const [content] = result.content as Array<{ type: string; text: string }>

        expect(content?.text).toContain('[query-logs]')
        expect(content?.text).toContain('Status Code: 500')
        expect(content?.text).toContain('Narrow the query and retry')
    })

    it('appends the hint even when the typed error is hidden behind Error.cause', () => {
        const original = new PostHogApiError({
            status: 503,
            statusText: 'Service Unavailable',
            body: 'upstream timeout',
            url: LOGS_QUERY_URL,
            method: 'POST',
        })
        const wrapped = wrapError('Failed to query logs', original)

        const result = handleToolError(wrapped, 'query-logs')
        const [content] = result.content as Array<{ type: string; text: string }>

        expect(content?.text).toContain('logs-count-ranges')
    })

    it('does not append a hint for a 4xx (no noise on recoverable input errors)', () => {
        const error = new PostHogValidationError({
            detail: 'invalid filter',
            attr: 'filterGroup',
            code: 'invalid',
            extra: undefined,
            url: LOGS_QUERY_URL,
            method: 'POST',
        })

        const result = handleToolError(error, 'query-logs')
        const [content] = result.content as Array<{ type: string; text: string }>

        expect(content?.text).not.toContain('Narrow the query and retry')
    })

    it('does not append a hint for a 5xx on an unrelated tool', () => {
        const error = new PostHogApiError({
            status: 500,
            statusText: 'Internal Server Error',
            body: 'boom',
            url: 'https://us.posthog.com/api/projects/2/insights/',
            method: 'GET',
        })

        const result = handleToolError(error, 'insights-list')
        const [content] = result.content as Array<{ type: string; text: string }>

        expect(content?.text).not.toContain('Narrow the query and retry')
    })
})
