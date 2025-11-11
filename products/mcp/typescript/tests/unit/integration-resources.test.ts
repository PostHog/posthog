import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { beforeEach, describe, expect, it } from 'vitest'

import { registerIntegrationResources } from '@/resources/integration'
import { getSupportedFrameworks } from '@/resources/integration/framework-mappings'
import { ResourceUri, WORKFLOW_NEXT_STEP_MESSAGE } from '@/resources/integration/index'
import type { Context } from '@/tools/types'

const FRAMEWORK_TEMPLATE_VARIABLE = '{framework}'

const createMockContext = (): Context => ({
    api: {} as any,
    cache: {} as any,
    env: {
        INKEEP_API_KEY: undefined,
    },
    stateManager: {} as any,
    sessionManager: {} as any,
})

describe('Integration Resources - Workflow Sequence', () => {
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

    it('should append next step URI to first workflow', async () => {
        const resources = (server as any)._registeredResources
        const resource = resources[ResourceUri.WORKFLOW_SETUP_BEGIN]
        expect(resource).toBeTruthy()

        const result = await resource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_BEGIN))
        const content = result.contents[0].text

        // Verify content is loaded from ZIP and contains expected workflow content
        expect(content).toBeTruthy()
        expect(content.length).toBeGreaterThan(0)
        expect(content).toContain(WORKFLOW_NEXT_STEP_MESSAGE)
        expect(content).toContain(ResourceUri.WORKFLOW_SETUP_EDIT)
    }, 30000) // 30 second timeout for network request

    it('should append next step URI to middle workflow', async () => {
        const resources = (server as any)._registeredResources
        const resource = resources[ResourceUri.WORKFLOW_SETUP_EDIT]
        expect(resource).toBeTruthy()

        const result = await resource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_EDIT))
        const content = result.contents[0].text

        // Verify content is loaded from ZIP and contains expected workflow content
        expect(content).toBeTruthy()
        expect(content.length).toBeGreaterThan(0)
        expect(content).toContain(WORKFLOW_NEXT_STEP_MESSAGE)
        expect(content).toContain(ResourceUri.WORKFLOW_SETUP_REVISE)
    }, 30000) // 30 second timeout for network request

    it('should not append next step URI to last workflow', async () => {
        const resources = (server as any)._registeredResources
        const resource = resources[ResourceUri.WORKFLOW_SETUP_REVISE]
        expect(resource).toBeTruthy()

        const result = await resource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_REVISE))
        const content = result.contents[0].text

        // Verify content is loaded from ZIP and does not contain next step
        expect(content).toBeTruthy()
        expect(content.length).toBeGreaterThan(0)
        expect(content).not.toContain(WORKFLOW_NEXT_STEP_MESSAGE)
    }, 30000) // 30 second timeout for network request

    it('should load workflow content from markdown files', async () => {
        const resources = (server as any)._registeredResources
        const beginResource = resources[ResourceUri.WORKFLOW_SETUP_BEGIN]
        const editResource = resources[ResourceUri.WORKFLOW_SETUP_EDIT]
        const reviseResource = resources[ResourceUri.WORKFLOW_SETUP_REVISE]

        const beginResult = await beginResource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_BEGIN))
        const editResult = await editResource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_EDIT))
        const reviseResult = await reviseResource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_REVISE))

        // Verify all workflows load content from ZIP
        expect(beginResult.contents[0].text).toBeTruthy()
        expect(beginResult.contents[0].text.length).toBeGreaterThan(0)

        expect(editResult.contents[0].text).toBeTruthy()
        expect(editResult.contents[0].text.length).toBeGreaterThan(0)

        expect(reviseResult.contents[0].text).toBeTruthy()
        expect(reviseResult.contents[0].text.length).toBeGreaterThan(0)
    }, 30000) // 30 second timeout for network request
})

describe('Integration Resources - Resource Templates', () => {
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

    describe('Framework completion', () => {
        it('should provide framework completion for docs template', async () => {
            const templates = Object.values((server as any)._registeredResourceTemplates)
            const template = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(ResourceUri.DOCS_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, ''))
            ) as any
            expect(template).toBeTruthy()

            const completeCallback = template.resourceTemplate.completeCallback('framework')
            expect(completeCallback).toBeTruthy()

            const frameworks = await completeCallback('')
            const expectedFrameworks = getSupportedFrameworks()

            expect(frameworks).toEqual(expectedFrameworks)
            expect(frameworks.length).toBeGreaterThan(0)
        })

        it('should provide framework completion for example projects template', async () => {
            const templates = Object.values((server as any)._registeredResourceTemplates)
            const template = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, ''))
            ) as any
            expect(template).toBeTruthy()

            const completeCallback = template.resourceTemplate.completeCallback('framework')
            expect(completeCallback).toBeTruthy()

            const frameworks = await completeCallback('')
            const expectedFrameworks = getSupportedFrameworks()

            expect(frameworks).toEqual(expectedFrameworks)
            expect(frameworks.length).toBeGreaterThan(0)
        })
    })

    describe('Resource listing', () => {
        it('should list all framework docs resources', async () => {
            const templates = Object.values((server as any)._registeredResourceTemplates)
            const template = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(ResourceUri.DOCS_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, ''))
            ) as any
            expect(template).toBeTruthy()

            const listCallback = template.resourceTemplate.listCallback
            expect(listCallback).toBeTruthy()

            const result = await listCallback({})
            const frameworks = getSupportedFrameworks()

            expect(result.resources).toHaveLength(frameworks.length)

            for (const framework of frameworks) {
                const expectedUri = ResourceUri.DOCS_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, framework)
                const resource = result.resources.find((r: any) => r.uri === expectedUri)
                expect(resource).toBeTruthy()
            }
        })

        it('should list all framework example project resources', async () => {
            const templates = Object.values((server as any)._registeredResourceTemplates)
            const template = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, ''))
            ) as any
            expect(template).toBeTruthy()

            const listCallback = template.resourceTemplate.listCallback
            expect(listCallback).toBeTruthy()

            const result = await listCallback({})
            const frameworks = getSupportedFrameworks()

            expect(result.resources).toHaveLength(frameworks.length)

            for (const framework of frameworks) {
                const expectedUri = ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                    FRAMEWORK_TEMPLATE_VARIABLE,
                    framework
                )
                const resource = result.resources.find((r: any) => r.uri === expectedUri)
                expect(resource).toBeTruthy()
            }
        })

        it('should generate correct URIs for each framework', async () => {
            const templates = Object.values((server as any)._registeredResourceTemplates)
            const docsTemplate = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(ResourceUri.DOCS_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, ''))
            ) as any
            const examplesTemplate = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, ''))
            ) as any

            const docsResult = await docsTemplate.resourceTemplate.listCallback({})
            const examplesResult = await examplesTemplate.resourceTemplate.listCallback({})

            const frameworks = getSupportedFrameworks()
            for (const framework of frameworks) {
                const expectedDocsUri = ResourceUri.DOCS_FRAMEWORK.replace(FRAMEWORK_TEMPLATE_VARIABLE, framework)
                const docsResource = docsResult.resources.find((r: any) => r.uri === expectedDocsUri)
                expect(docsResource).toBeTruthy()

                const expectedExamplesUri = ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                    FRAMEWORK_TEMPLATE_VARIABLE,
                    framework
                )
                const examplesResource = examplesResult.resources.find((r: any) => r.uri === expectedExamplesUri)
                expect(examplesResource).toBeTruthy()
            }
        })
    })
})
