import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { describe, expect, it, beforeEach } from 'vitest'
import { registerIntegrationResources } from '@/resources/integration'
import { ResourceUri, WORKFLOW_NEXT_STEP_MESSAGE } from '@/resources/integration/index'
import { getSupportedFrameworks } from '@/resources/integration/framework-mappings'
import type { Context } from '@/tools/types'

import workflowBegin from '@/resources/integration/workflow-guides/1.0-event-setup-begin.md'
import workflowEdit from '@/resources/integration/workflow-guides/1.1-event-setup-edit.md'
import workflowRevise from '@/resources/integration/workflow-guides/1.2-event-setup-revise.md'

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
        expect(resource).toBeDefined()

        const result = await resource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_BEGIN))
        const content = result.contents[0].text

        expect(content).toContain(workflowBegin)
        expect(content).toContain(WORKFLOW_NEXT_STEP_MESSAGE)
        expect(content).toContain(ResourceUri.WORKFLOW_SETUP_EDIT)
    })

    it('should append next step URI to middle workflow', async () => {
        const resources = (server as any)._registeredResources
        const resource = resources[ResourceUri.WORKFLOW_SETUP_EDIT]
        expect(resource).toBeDefined()

        const result = await resource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_EDIT))
        const content = result.contents[0].text

        expect(content).toContain(workflowEdit)
        expect(content).toContain(WORKFLOW_NEXT_STEP_MESSAGE)
        expect(content).toContain(ResourceUri.WORKFLOW_SETUP_REVISE)
    })

    it('should not append next step URI to last workflow', async () => {
        const resources = (server as any)._registeredResources
        const resource = resources[ResourceUri.WORKFLOW_SETUP_REVISE]
        expect(resource).toBeDefined()

        const result = await resource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_REVISE))
        const content = result.contents[0].text

        expect(content).toContain(workflowRevise)
        expect(content).not.toContain(WORKFLOW_NEXT_STEP_MESSAGE)
    })

    it('should load workflow content from markdown files', async () => {
        const resources = (server as any)._registeredResources
        const beginResource = resources[ResourceUri.WORKFLOW_SETUP_BEGIN]
        const editResource = resources[ResourceUri.WORKFLOW_SETUP_EDIT]
        const reviseResource = resources[ResourceUri.WORKFLOW_SETUP_REVISE]

        const beginResult = await beginResource.readCallback(
            new URL(ResourceUri.WORKFLOW_SETUP_BEGIN)
        )
        const editResult = await editResource.readCallback(new URL(ResourceUri.WORKFLOW_SETUP_EDIT))
        const reviseResult = await reviseResource.readCallback(
            new URL(ResourceUri.WORKFLOW_SETUP_REVISE)
        )

        expect(beginResult.contents[0].text).toContain(workflowBegin)
        expect(editResult.contents[0].text).toContain(workflowEdit)
        expect(reviseResult.contents[0].text).toContain(workflowRevise)
    })
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
            expect(template).toBeDefined()

            const completeCallback = template.resourceTemplate.completeCallback('framework')
            expect(completeCallback).toBeDefined()

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
                    .startsWith(
                        ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                            FRAMEWORK_TEMPLATE_VARIABLE,
                            ''
                        )
                    )
            ) as any
            expect(template).toBeDefined()

            const completeCallback = template.resourceTemplate.completeCallback('framework')
            expect(completeCallback).toBeDefined()

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
            expect(template).toBeDefined()

            const listCallback = template.resourceTemplate.listCallback
            expect(listCallback).toBeDefined()

            const result = await listCallback({})
            const frameworks = getSupportedFrameworks()

            expect(result.resources).toHaveLength(frameworks.length)

            for (const framework of frameworks) {
                const expectedUri = ResourceUri.DOCS_FRAMEWORK.replace(
                    FRAMEWORK_TEMPLATE_VARIABLE,
                    framework
                )
                const resource = result.resources.find((r: any) => r.uri === expectedUri)
                expect(resource).toBeDefined()
            }
        })

        it('should list all framework example project resources', async () => {
            const templates = Object.values((server as any)._registeredResourceTemplates)
            const template = templates.find((t: any) =>
                t.resourceTemplate.uriTemplate
                    .toString()
                    .startsWith(
                        ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                            FRAMEWORK_TEMPLATE_VARIABLE,
                            ''
                        )
                    )
            ) as any
            expect(template).toBeDefined()

            const listCallback = template.resourceTemplate.listCallback
            expect(listCallback).toBeDefined()

            const result = await listCallback({})
            const frameworks = getSupportedFrameworks()

            expect(result.resources).toHaveLength(frameworks.length)

            for (const framework of frameworks) {
                const expectedUri = ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                    FRAMEWORK_TEMPLATE_VARIABLE,
                    framework
                )
                const resource = result.resources.find((r: any) => r.uri === expectedUri)
                expect(resource).toBeDefined()
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
                    .startsWith(
                        ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                            FRAMEWORK_TEMPLATE_VARIABLE,
                            ''
                        )
                    )
            ) as any

            const docsResult = await docsTemplate.resourceTemplate.listCallback({})
            const examplesResult = await examplesTemplate.resourceTemplate.listCallback({})

            const frameworks = getSupportedFrameworks()
            for (const framework of frameworks) {
                const expectedDocsUri = ResourceUri.DOCS_FRAMEWORK.replace(
                    FRAMEWORK_TEMPLATE_VARIABLE,
                    framework
                )
                const docsResource = docsResult.resources.find(
                    (r: any) => r.uri === expectedDocsUri
                )
                expect(docsResource).toBeDefined()

                const expectedExamplesUri = ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                    FRAMEWORK_TEMPLATE_VARIABLE,
                    framework
                )
                const examplesResource = examplesResult.resources.find(
                    (r: any) => r.uri === expectedExamplesUri
                )
                expect(examplesResource).toBeDefined()
            }
        })
    })
})
