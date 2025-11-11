import { type McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js'
import { type Unzipped, strFromU8, unzipSync } from 'fflate'

import type { Context } from '@/tools/types'

import {
    EXAMPLES_MARKDOWN_URL,
    FRAMEWORK_DOCS,
    FRAMEWORK_MARKDOWN_FILES,
    WORKFLOW_GUIDE_FILES,
    getSupportedFrameworks,
    getSupportedFrameworksList,
    isSupportedFramework,
} from './framework-mappings'

/**
 * Resource URI constants for PostHog integration resources
 */
export enum ResourceUri {
    // Workflow guides
    WORKFLOW_SETUP_BEGIN = 'posthog://integration/workflow/setup/begin',
    WORKFLOW_SETUP_EDIT = 'posthog://integration/workflow/setup/edit',
    WORKFLOW_SETUP_REVISE = 'posthog://integration/workflow/setup/revise',

    // Documentation (static)
    DOCS_IDENTIFY = 'posthog://integration/docs/features/identify',

    // Framework-specific content
    DOCS_FRAMEWORK = 'posthog://integration/docs/frameworks/{framework}',
    EXAMPLE_PROJECT_FRAMEWORK = 'posthog://integration/example-projects/{framework}',
}

/**
 * Message appended to workflow resources to indicate the next step
 */
export const WORKFLOW_NEXT_STEP_MESSAGE = 'Upon completion, access the following resource to continue:'

/**
 * URL to the identify() documentation
 */
const IDENTIFY_USERS_DOCS_URL = 'https://posthog.com/docs/getting-started/identify-users.md'

// Cache for the examples markdown ZIP contents (includes both examples and prompts)
let cachedExamplesMarkdown: Unzipped | null = null

/**
 * Fetches documentation content from a URL with error handling
 */
async function fetchDocumentation(url: string): Promise<string> {
    const response = await fetch(url)

    if (!response.ok) {
        throw new Error(`Failed to fetch documentation: ${response.statusText}`)
    }

    return response.text()
}

/**
 * Fetches and caches the examples markdown ZIP at startup
 * This ZIP contains both example projects and LLM prompts
 */
async function fetchExamplesMarkdown(): Promise<Unzipped> {
    if (cachedExamplesMarkdown) {
        return cachedExamplesMarkdown
    }

    const response = await fetch(EXAMPLES_MARKDOWN_URL)

    if (!response.ok) {
        throw new Error(`Failed to fetch examples markdown: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    cachedExamplesMarkdown = unzipSync(uint8Array)

    return cachedExamplesMarkdown
}

// Define workflow sequence - files will be loaded from ZIP
const workflowSequence = [
    {
        uri: ResourceUri.WORKFLOW_SETUP_BEGIN,
        name: 'Event Setup - Begin',
        description: 'Start the event tracking setup process',
        file: WORKFLOW_GUIDE_FILES.BEGIN,
    },
    {
        uri: ResourceUri.WORKFLOW_SETUP_EDIT,
        name: 'Event Setup - Edit',
        description: 'Edit files to add PostHog event tracking',
        file: WORKFLOW_GUIDE_FILES.EDIT,
    },
    {
        uri: ResourceUri.WORKFLOW_SETUP_REVISE,
        name: 'Event Setup - Revise',
        description: 'Review and fix any errors in the implementation',
        file: WORKFLOW_GUIDE_FILES.REVISE,
    },
]

/**
 * Registers all PostHog integration resources with the MCP server
 */
// oxlint-disable-next-line @typescript-eslint/no-unused-vars
export function registerIntegrationResources(server: McpServer, _context: Context): void {
    // Fetch examples markdown (includes both examples and prompts) at startup
    fetchExamplesMarkdown().catch((error) => {
        console.error('Failed to fetch examples markdown:', error)
    })

    // Register workflow resources with automatic next step appending
    workflowSequence.forEach((workflow, i) => {
        const nextWorkflow = workflowSequence[i + 1]

        server.registerResource(
            workflow.name,
            workflow.uri,
            {
                mimeType: 'text/markdown',
                description: workflow.description,
            },
            async (uri) => {
                // Fetch the examples ZIP which includes prompts (from cache if available)
                const examplesZip = await fetchExamplesMarkdown()

                // Read the workflow file from the ZIP
                const promptData = examplesZip[workflow.file]
                if (!promptData) {
                    throw new Error(`Workflow file "${workflow.file}" not found in examples archive`)
                }

                const content = strFromU8(promptData)

                // Append next step URI if there is a next workflow
                const finalContent = nextWorkflow
                    ? `${content}\n\n---\n\n**${WORKFLOW_NEXT_STEP_MESSAGE}** ${nextWorkflow.uri}`
                    : content

                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: finalContent,
                        },
                    ],
                }
            }
        )
    })

    // Register the PostHog docs resource - fetch from URL with framework template
    server.registerResource(
        'Integration docs',
        new ResourceTemplate(ResourceUri.DOCS_FRAMEWORK, {
            list: async () => {
                const frameworks = getSupportedFrameworks()
                return {
                    resources: frameworks.map((framework) => ({
                        uri: ResourceUri.DOCS_FRAMEWORK.replace('{framework}', framework),
                        name: `PostHog ${framework} integration documentation`,
                        description: `PostHog integration documentation for ${framework}`,
                        mimeType: 'text/markdown',
                    })),
                }
            },
            complete: {
                framework: async () => getSupportedFrameworks(),
            },
        }),
        {
            mimeType: 'text/markdown',
            description: `PostHog integration documentation for a specific framework. Supported frameworks: ${getSupportedFrameworksList()}`,
        },
        async (uri, { framework }) => {
            // Ensure framework is a string
            const frameworkStr = Array.isArray(framework) ? framework[0] : framework
            if (!frameworkStr || !isSupportedFramework(frameworkStr)) {
                throw new Error(
                    `Framework "${frameworkStr || 'unknown'}" is not supported yet. Currently supported: ${getSupportedFrameworksList()}`
                )
            }

            const docsUrl = FRAMEWORK_DOCS[frameworkStr]
            const content = await fetchDocumentation(docsUrl)
            return {
                contents: [
                    {
                        uri: uri.toString(),
                        text: content,
                    },
                ],
            }
        }
    )

    // Register the identify users documentation resource
    server.registerResource(
        'Identify Users docs',
        ResourceUri.DOCS_IDENTIFY,
        {
            mimeType: 'text/markdown',
            description: 'PostHog documentation on identifying users',
        },
        async (uri) => {
            const content = await fetchDocumentation(IDENTIFY_USERS_DOCS_URL)
            return {
                contents: [
                    {
                        uri: uri.toString(),
                        text: content,
                    },
                ],
            }
        }
    )

    // Register example project resource with framework template
    server.registerResource(
        'Example project',
        new ResourceTemplate(ResourceUri.EXAMPLE_PROJECT_FRAMEWORK, {
            list: async () => {
                const frameworks = getSupportedFrameworks()
                return {
                    resources: frameworks.map((framework) => ({
                        uri: ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace('{framework}', framework),
                        name: `PostHog ${framework} example project`,
                        description: `Example project code for ${framework}`,
                        mimeType: 'text/markdown',
                    })),
                }
            },
            complete: {
                framework: async () => getSupportedFrameworks(),
            },
        }),
        {
            mimeType: 'text/markdown',
            description: `PostHog example project files for a specific framework. Supported frameworks: ${getSupportedFrameworksList()}`,
        },
        async (uri, { framework }) => {
            // Ensure framework is a string
            const frameworkStr = Array.isArray(framework) ? framework[0] : framework
            if (!frameworkStr || !isSupportedFramework(frameworkStr)) {
                throw new Error(
                    `Framework "${frameworkStr || 'unknown'}" is not supported yet. Currently supported: ${getSupportedFrameworksList()}`
                )
            }

            // Get the cached markdown ZIP (or fetch if not yet cached)
            const markdownZip = await fetchExamplesMarkdown()
            const markdownFilename = FRAMEWORK_MARKDOWN_FILES[frameworkStr]

            // Read the markdown file from the ZIP
            const markdownData = markdownZip[markdownFilename]
            if (!markdownData) {
                throw new Error(`Markdown file "${markdownFilename}" not found in examples archive`)
            }

            const markdown = strFromU8(markdownData)

            return {
                contents: [
                    {
                        uri: uri.toString(),
                        text: markdown,
                    },
                ],
            }
        }
    )
}
