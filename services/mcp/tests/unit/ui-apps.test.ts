import { describe, expect, it, vi } from 'vitest'

import { buildAppStubHtml } from '@/resources/ui-apps'

describe('ui-apps', () => {
    describe('buildAppStubHtml', () => {
        it('generates correct stub HTML for production base URL', () => {
            const html = buildAppStubHtml('debug', 'https://mcp.posthog.com')
            expect(html).toMatchInlineSnapshot(`
                "<!DOCTYPE html>
                <html lang="en"><head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <link rel="stylesheet" href="https://mcp.posthog.com/ui-apps/debug/styles.css">
                </head><body>
                <div id="root"></div>
                <script src="https://mcp.posthog.com/ui-apps/debug/main.js"></script>
                </body></html>"
            `)
        })

        it('generates correct stub HTML for local development', () => {
            const html = buildAppStubHtml('query-results', 'http://localhost:8787')
            expect(html).toMatchInlineSnapshot(`
                "<!DOCTYPE html>
                <html lang="en"><head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <link rel="stylesheet" href="http://localhost:8787/ui-apps/query-results/styles.css">
                </head><body>
                <div id="root"></div>
                <script src="http://localhost:8787/ui-apps/query-results/main.js"></script>
                </body></html>"
            `)
        })

        it('handles hyphenated app names', () => {
            const html = buildAppStubHtml('error-issue-list', 'https://mcp.posthog.com')
            expect(html).toContain('href="https://mcp.posthog.com/ui-apps/error-issue-list/styles.css"')
            expect(html).toContain('src="https://mcp.posthog.com/ui-apps/error-issue-list/main.js"')
        })

        it('produces valid HTML structure', () => {
            const html = buildAppStubHtml('debug', 'https://example.com')
            expect(html).toMatch(/^<!DOCTYPE html>/)
            expect(html).toContain('<html lang="en">')
            expect(html).toContain('<meta charset="UTF-8">')
            expect(html).toContain('<div id="root"></div>')
            expect(html).toContain('</body></html>')
        })

        it('uses script tag without type=module (IIFE format)', () => {
            const html = buildAppStubHtml('debug', 'https://example.com')
            expect(html).toContain('<script src=')
            expect(html).not.toContain('type="module"')
        })
    })

    describe('registerUiAppResources', () => {
        function createMockServer(): {
            registerResource: ReturnType<typeof vi.fn>
        } {
            return { registerResource: vi.fn() }
        }

        function createMockContext(env: Record<string, string | undefined> = {}): {
            env: Record<string, string | undefined>
        } {
            return {
                env: {
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                    POSTHOG_UI_APPS_TOKEN: undefined,
                    INKEEP_API_KEY: undefined,
                    POSTHOG_API_BASE_URL: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                    ...env,
                },
            }
        }

        it('skips registration when MCP_APPS_BASE_URL is not set', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext()
            const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

            await registerUiAppResources(server as any, context as any)

            expect(server.registerResource).not.toHaveBeenCalled()
            expect(warnSpy).toHaveBeenCalledWith(
                'MCP_APPS_BASE_URL is not set — UI app resources will not be registered'
            )
            warnSpy.mockRestore()
        })

        it('registers all apps when MCP_APPS_BASE_URL is set', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({ MCP_APPS_BASE_URL: 'https://mcp.posthog.com' })

            await registerUiAppResources(server as any, context as any)

            expect(server.registerResource).toHaveBeenCalledTimes(21)
        })

        it('registers apps with correct names and URIs', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({ MCP_APPS_BASE_URL: 'https://mcp.posthog.com' })

            await registerUiAppResources(server as any, context as any)

            const registeredNames = server.registerResource.mock.calls.map((call: unknown[]) => call[0])
            expect(registeredNames).toContain('MCP Apps Debug')
            expect(registeredNames).toContain('Query Results')
            expect(registeredNames).toContain('Feature flag')
            expect(registeredNames).toContain('Experiment results')
        })

        it('includes base URL in CSP resourceDomains', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({ MCP_APPS_BASE_URL: 'https://mcp.posthog.com' })

            await registerUiAppResources(server as any, context as any)

            // Call the resource handler for the first registered app
            const handler = server.registerResource.mock.calls[0]![3]
            const result = await handler(new URL('ui://posthog/debug.html'))

            expect(result.contents[0]._meta.ui.csp.resourceDomains).toContain('https://mcp.posthog.com')
        })

        it('includes analytics URL in CSP when set', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({
                MCP_APPS_BASE_URL: 'https://mcp.posthog.com',
                POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: 'https://us.i.posthog.com',
            })

            await registerUiAppResources(server as any, context as any)

            const handler = server.registerResource.mock.calls[0]![3]
            const result = await handler(new URL('ui://posthog/debug.html'))

            expect(result.contents[0]._meta.ui.csp.resourceDomains).toContain('https://us.i.posthog.com')
            expect(result.contents[0]._meta.ui.csp.connectDomains).toContain('https://us.i.posthog.com')
        })

        it('omits analytics URL from CSP when not set', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({ MCP_APPS_BASE_URL: 'https://mcp.posthog.com' })

            await registerUiAppResources(server as any, context as any)

            const handler = server.registerResource.mock.calls[0]![3]
            const result = await handler(new URL('ui://posthog/debug.html'))

            expect(result.contents[0]._meta.ui.csp.resourceDomains).toEqual(['https://mcp.posthog.com'])
            expect(result.contents[0]._meta.ui.csp.connectDomains).toEqual([])
        })

        it('resource handler returns stub HTML with correct base URL', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({ MCP_APPS_BASE_URL: 'https://mcp.posthog.com' })

            await registerUiAppResources(server as any, context as any)

            // Find the debug app registration
            const debugCall = server.registerResource.mock.calls.find((call: unknown[]) => call[0] === 'MCP Apps Debug')
            const handler = debugCall![3]
            const result = await handler(new URL('ui://posthog/debug.html'))

            expect(result.contents[0].text).toMatchInlineSnapshot(`
                "<!DOCTYPE html>
                <html lang="en"><head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <link rel="stylesheet" href="https://mcp.posthog.com/ui-apps/debug/styles.css">
                </head><body>
                <div id="root"></div>
                <script src="https://mcp.posthog.com/ui-apps/debug/main.js"></script>
                </body></html>"
            `)
        })

        it('resource handler returns correct MIME type', async () => {
            const { registerUiAppResources } = await import('@/resources/ui-apps')
            const server = createMockServer()
            const context = createMockContext({ MCP_APPS_BASE_URL: 'https://mcp.posthog.com' })

            await registerUiAppResources(server as any, context as any)

            const handler = server.registerResource.mock.calls[0]![3]
            const result = await handler(new URL('ui://posthog/debug.html'))

            expect(result.contents[0].mimeType).toBe('text/html;profile=mcp-app')
        })
    })
})
