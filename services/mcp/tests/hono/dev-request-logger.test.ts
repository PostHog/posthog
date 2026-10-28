import { Hono } from 'hono'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { devRequestLogger } from '@/hono/middleware'

describe('devRequestLogger', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('logs request metadata without exposing credentials or consuming the body', async () => {
        const consoleInfo = vi.spyOn(console, 'info').mockImplementation(() => undefined)
        const app = new Hono()
        app.use('*', devRequestLogger)
        app.post('/mcp', async (c) => c.json(await c.req.json()))

        const response = await app.request('/mcp?token=query-secret&project=123', {
            method: 'POST',
            headers: {
                accept: 'application/json',
                authorization: 'Bearer header-secret',
                'content-type': 'application/json',
                'x-csrftoken': 'csrf-secret',
                'x-posthog-session-id': 'session-secret',
                'x-tool-credential': 'tool-secret',
            },
            body: JSON.stringify({ password: 'body-secret' }),
        })

        expect(await response.json()).toEqual({ password: 'body-secret' })
        expect(consoleInfo).toHaveBeenCalledOnce()

        const logOutput = JSON.stringify(consoleInfo.mock.calls[0])
        expect(logOutput).toContain('"pathname":"/mcp"')
        expect(logOutput).toContain('"queryParameters":["token","project"]')
        expect(logOutput).toContain('"accept":"application/json"')
        expect(logOutput).toContain('"present":true')
        expect(logOutput).toContain('"contentType":"application/json"')
        expect(logOutput).toContain('"x-csrftoken":"[REDACTED]"')
        expect(logOutput).toContain('"x-posthog-session-id":"[REDACTED]"')
        expect(logOutput).toContain('"x-tool-credential":"[REDACTED]"')
        expect(logOutput).not.toContain('query-secret')
        expect(logOutput).not.toContain('header-secret')
        expect(logOutput).not.toContain('csrf-secret')
        expect(logOutput).not.toContain('session-secret')
        expect(logOutput).not.toContain('tool-secret')
        expect(logOutput).not.toContain('body-secret')
    })
})
