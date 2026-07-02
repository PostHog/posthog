import { describe, expect, it, vi } from 'vitest'

import { handleToolError, parseApiErrorDetail, PostHogApiError } from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))

function textOf(result: ReturnType<typeof handleToolError>): string {
    const [content] = result.content as Array<{ type: string; text: string }>
    return content?.text ?? ''
}

describe('handleToolError for plan-gated (402) API errors', () => {
    function paidError(body: string): PostHogApiError {
        return new PostHogApiError({
            status: 402,
            statusText: 'Payment Required',
            body,
            url: 'https://us.posthog.com/api/projects/2/activity_log/',
            method: 'GET',
        })
    }

    it('surfaces the plan-gating detail on its own, not the raw "Request failed" dump', () => {
        const error = paidError(JSON.stringify({ detail: 'Audit logs requires a paid PostHog plan.' }))

        const result = handleToolError(error, 'activity-log-list')

        expect(result.isError).toBe(true)
        expect(textOf(result)).toBe('Error: [activity-log-list]: Audit logs requires a paid PostHog plan.')
        // A 402 is expected plan state, not a bug — never fingerprint it into error tracking.
        expect(captureException).not.toHaveBeenCalled()
    })

    it('falls back to a generic upgrade message when the body is not the expected JSON', () => {
        const result = handleToolError(paidError('<html>gateway</html>'), 'activity-log-list')

        expect(textOf(result)).toBe(
            'Error: [activity-log-list]: This feature requires a paid PostHog plan. Please upgrade to access it.'
        )
    })
})

describe('parseApiErrorDetail', () => {
    it('extracts a trimmed detail string from a PostHog API error body', () => {
        expect(parseApiErrorDetail(JSON.stringify({ detail: '  needs a plan  ' }))).toBe('needs a plan')
    })

    it('returns undefined for a non-JSON body or a missing/blank detail', () => {
        expect(parseApiErrorDetail('not json')).toBeUndefined()
        expect(parseApiErrorDetail(JSON.stringify({ detail: '   ' }))).toBeUndefined()
        expect(parseApiErrorDetail(JSON.stringify({ code: 'x' }))).toBeUndefined()
    })
})
