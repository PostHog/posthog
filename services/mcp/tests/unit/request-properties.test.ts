import { describe, expect, it } from 'vitest'

import { parseRequestProperties } from '@/lib/request-properties'

function makeRequest(opts: { url?: string; headers?: Record<string, string> } = {}): Request {
    return new Request(opts.url ?? 'https://mcp.posthog.com/mcp', { headers: opts.headers ?? {} })
}

describe('parseRequestProperties projectId validation', () => {
    // Regression: agents and copy-pasted setup snippets frequently send
    // placeholder strings for `x-posthog-project-id`. Caching them and
    // hitting `/api/projects/{id}/` produces a 400 PostHogValidationError per
    // distinct bad value — pure error-tracking noise.
    it.each([
        ['YOUR_POSTHOG_PROJECT_ID'],
        ['${POSTHOG_PROJECT_ID}'],
        ['your_project_id_here'],
        ['NaN'],
        ['BeConfident Prod'],
        ['phx_1234567890abcdef'],
        ['1.5'],
        ['-1'],
        ['+1'],
        [' '],
    ])('drops non-numeric placeholder %s from x-posthog-project-id', (value) => {
        const req = makeRequest({ headers: { 'x-posthog-project-id': value } })

        const props = parseRequestProperties(req, {})

        expect(props.projectId).toBeUndefined()
    })

    it.each([['YOUR_POSTHOG_PROJECT_ID'], ['NaN'], ['phx_1234567890abcdef']])(
        'drops non-numeric placeholder %s from project_id query param',
        (value) => {
            const req = makeRequest({ url: `https://mcp.posthog.com/mcp?project_id=${encodeURIComponent(value)}` })

            const props = parseRequestProperties(req, {})

            expect(props.projectId).toBeUndefined()
        }
    )

    it.each([['1'], ['456'], ['  789  ']])('accepts numeric project id %s', (value) => {
        const req = makeRequest({ headers: { 'x-posthog-project-id': value } })

        const props = parseRequestProperties(req, {})

        expect(props.projectId).toBe(value.trim())
    })

    it('prefers a numeric header over a query param', () => {
        const req = new Request('https://mcp.posthog.com/mcp?project_id=999', {
            headers: { 'x-posthog-project-id': '42' },
        })

        const props = parseRequestProperties(req, {})

        expect(props.projectId).toBe('42')
    })

    it('returns undefined when no project id is supplied', () => {
        const props = parseRequestProperties(makeRequest(), {})

        expect(props.projectId).toBeUndefined()
    })
})
