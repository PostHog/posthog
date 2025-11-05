import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { describe, expect, it, beforeEach } from 'vitest'
import { registerIntegrationResources } from '@/resources/integration'
import { ResourceUri } from '@/resources/integration/index'
import {
    getSupportedFrameworks,
    EXAMPLES_MARKDOWN_URL,
    FRAMEWORK_MARKDOWN_FILES,
} from '@/resources/integration/framework-mappings'
import type { Context } from '@/tools/types'
import { unzipSync, strFromU8 } from 'fflate'

const createMockContext = (): Context => ({
    api: {} as any,
    cache: {} as any,
    env: {
        INKEEP_API_KEY: undefined,
    },
    stateManager: {} as any,
    sessionManager: {} as any,
})

describe('Example Resources - Markdown Artifact Loading', () => {
    let server: McpServer
    let context: Context

    beforeEach(() => {
        server = new McpServer({
            name: 'Test Server',
            version: '1.0.0',
        })
        context = createMockContext()
        registerIntegrationResources(server, context)
    })

    it('should fetch and unzip the examples markdown artifact from GitHub releases', async () => {
        const response = await fetch(EXAMPLES_MARKDOWN_URL)
        expect(response.ok).toBe(true)

        const arrayBuffer = await response.arrayBuffer()
        const uint8Array = new Uint8Array(arrayBuffer)
        const unzipped = unzipSync(uint8Array)

        expect(unzipped).toBeDefined()
        expect(Object.keys(unzipped).length).toBeGreaterThan(0)
    }, 30000) // 30 second timeout for network request

    it('should contain markdown files for all supported frameworks', async () => {
        const response = await fetch(EXAMPLES_MARKDOWN_URL)
        const arrayBuffer = await response.arrayBuffer()
        const uint8Array = new Uint8Array(arrayBuffer)
        const unzipped = unzipSync(uint8Array)

        const frameworks = getSupportedFrameworks()

        for (const framework of frameworks) {
            const filename =
                FRAMEWORK_MARKDOWN_FILES[framework as keyof typeof FRAMEWORK_MARKDOWN_FILES]
            const fileData = unzipped[filename]
            expect(fileData).toBeDefined()
            expect(fileData!.length).toBeGreaterThan(0)
        }
    }, 30000)

    it('should load valid markdown content for each framework', async () => {
        const response = await fetch(EXAMPLES_MARKDOWN_URL)
        const arrayBuffer = await response.arrayBuffer()
        const uint8Array = new Uint8Array(arrayBuffer)
        const unzipped = unzipSync(uint8Array)

        const frameworks = getSupportedFrameworks()

        for (const framework of frameworks) {
            const filename =
                FRAMEWORK_MARKDOWN_FILES[framework as keyof typeof FRAMEWORK_MARKDOWN_FILES]
            const markdownData = unzipped[filename]
            expect(markdownData).toBeDefined()

            const markdown = strFromU8(markdownData!)
            expect(markdown).toBeTruthy()
            expect(markdown.length).toBeGreaterThan(0)

            // Verify markdown structure
            expect(markdown).toContain('# PostHog')
            expect(markdown).toContain('Repository: https://github.com/PostHog/examples')
            expect(markdown).toContain('```') // Should contain code blocks
        }
    }, 30000)

    it('should successfully retrieve example project resources via MCP', async () => {
        const templates = Object.values((server as any)._registeredResourceTemplates)
        const exampleTemplate = templates.find((t: any) =>
            t.resourceTemplate.uriTemplate
                .toString()
                .startsWith(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', ''))
        ) as any

        expect(exampleTemplate).toBeDefined()

        const frameworks = getSupportedFrameworks()

        for (const framework of frameworks) {
            const uri = new URL(
                ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', framework)
            )
            const result = await exampleTemplate.readCallback(uri, { framework })

            expect(result).toBeDefined()
            expect(result.contents).toHaveLength(1)
            expect(result.contents[0].text).toBeTruthy()
            expect(result.contents[0].text).toContain('# PostHog')
            expect(result.contents[0].uri).toBe(uri.toString())
        }
    }, 30000)

    it('should handle missing framework files gracefully', async () => {
        const templates = Object.values((server as any)._registeredResourceTemplates)
        const exampleTemplate = templates.find((t: any) =>
            t.resourceTemplate.uriTemplate
                .toString()
                .startsWith(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', ''))
        ) as any

        const invalidFramework = 'invalid-framework-xyz'
        const uri = new URL(
            ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', invalidFramework)
        )

        await expect(
            exampleTemplate.readCallback(uri, { framework: invalidFramework })
        ).rejects.toThrow(/is not supported yet/)
    }, 30000)

    it('should cache the markdown ZIP and reuse it', async () => {
        const templates = Object.values((server as any)._registeredResourceTemplates)
        const exampleTemplate = templates.find((t: any) =>
            t.resourceTemplate.uriTemplate
                .toString()
                .startsWith(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', ''))
        ) as any

        const framework = 'nextjs-app-router'

        // First call should fetch and cache
        const uri1 = new URL(
            ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', framework)
        )
        const result1 = await exampleTemplate.readCallback(uri1, { framework })
        expect(result1.contents[0].text).toBeTruthy()

        // Second call should use cache (we can't directly verify caching, but we verify it works)
        const uri2 = new URL(
            ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', framework)
        )
        const result2 = await exampleTemplate.readCallback(uri2, { framework })
        expect(result2.contents[0].text).toBeTruthy()

        // Results should be identical
        expect(result1.contents[0].text).toBe(result2.contents[0].text)
    }, 30000)
})
