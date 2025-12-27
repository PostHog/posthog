import { describe, expect, it, vi } from 'vitest'

import { createWelcomeHandler } from '@/server/handlers/welcome'
import { MCP_DOCS_URL } from '@/lib/constants'
import { createMockRequest, createMockResponse } from '../fixtures'

describe('welcome handler', () => {
    describe('createWelcomeHandler', () => {
        it('returns HTML content', () => {
            const handler = createWelcomeHandler()
            const req = createMockRequest()
            const res = createMockResponse()

            handler(req, res, vi.fn())

            expect(res._headers['Content-Type']).toBe('text/html')
        })

        it('includes docs URL in response', () => {
            const handler = createWelcomeHandler()
            const req = createMockRequest()
            const res = createMockResponse()

            handler(req, res, vi.fn())

            expect(res._body).toContain(MCP_DOCS_URL)
            expect(res._body).toContain('Welcome to the PostHog MCP Server')
        })

        it('includes link to documentation', () => {
            const handler = createWelcomeHandler()
            const req = createMockRequest()
            const res = createMockResponse()

            handler(req, res, vi.fn())

            expect(res._body).toContain(`href="${MCP_DOCS_URL}"`)
        })
    })
})
