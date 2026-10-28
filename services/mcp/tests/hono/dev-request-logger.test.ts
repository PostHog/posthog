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

    it.each([
        { ui: { mimeTypes: ['text/html;profile=mcp-app'] }, supported: true },
        { ui: { mimeTypes: ['text/html'] }, supported: false },
        { ui: { mimeTypes: 'text/html;profile=mcp-app' }, supported: false },
        { ui: undefined, supported: false },
    ])('logs only the selected UI capability fields for %j', async ({ ui, supported }) => {
        const consoleInfo = vi.spyOn(console, 'info').mockImplementation(() => undefined)
        const app = new Hono()
        app.use('*', devRequestLogger)
        app.post('/mcp', (c) => c.json({ ok: true }))

        await app.request('/mcp', {
            method: 'POST',
            headers: { 'content-type': 'application/json', authorization: 'Bearer secret-token' },
            body: JSON.stringify({
                id: 1,
                method: 'initialize',
                params: {
                    clientInfo: { name: 'openai-mcp', version: '1.0' },
                    protocolVersion: '2025-11-25',
                    capabilities: { extensions: { 'io.modelcontextprotocol/ui': ui }, secret: 'capability-secret' },
                    secret: 'body-secret',
                },
            }),
        })

        expect(consoleInfo).toHaveBeenCalledWith(
            '[MCP dev]',
            expect.objectContaining({
                mcpClient: expect.objectContaining({
                    clientName: 'openai-mcp',
                    clientVersion: '1.0',
                    protocolVersion: '2025-11-25',
                    uiSupported: supported,
                    uiCapabilityDeclared: ui !== undefined,
                }),
            })
        )
        const logOutput = JSON.stringify(consoleInfo.mock.calls)
        expect(logOutput).not.toContain('secret-token')
        expect(logOutput).not.toContain('capability-secret')
        expect(logOutput).not.toContain('body-secret')
    })
})
