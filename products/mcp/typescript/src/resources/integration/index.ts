import { type McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Context } from '@/tools/types'
import {
    FRAMEWORK_DOCS,
    EXAMPLES_MONOREPO_URL,
    FRAMEWORK_EXAMPLE_PATHS,
    isSupportedFramework,
    getSupportedFrameworks,
    getSupportedFrameworksList,
} from './framework-mappings'
import { convertSubfolderToMarkdown } from './repo-to-md'
import { unzipSync, type Unzipped } from 'fflate'

// Import workflow markdown files
import workflowBegin from './workflow-guides/1.0-event-setup-begin.md'
import workflowEdit from './workflow-guides/1.1-event-setup-edit.md'
import workflowRevise from './workflow-guides/1.2-event-setup-revise.md'

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
export const WORKFLOW_NEXT_STEP_MESSAGE =
    'Upon completion, access the following resource to continue:'

/**
 * URL to the identify() documentation
 */
const IDENTIFY_USERS_DOCS_URL = 'https://posthog.com/docs/getting-started/identify-users.md'

// Cache for the examples monorepo ZIP contents
let cachedExamplesRepo: Unzipped | null = null

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
 * Fetches and caches the examples monorepo ZIP at startup
 */
async function fetchExamplesMonorepo(): Promise<Unzipped> {
    if (cachedExamplesRepo) {
        return cachedExamplesRepo
    }

    console.log('Fetching PostHog examples monorepo...')
    const response = await fetch(EXAMPLES_MONOREPO_URL)

    if (!response.ok) {
        throw new Error(`Failed to fetch examples monorepo: ${response.statusText}`)
    }

    const arrayBuffer = await response.arrayBuffer()
    const uint8Array = new Uint8Array(arrayBuffer)
    cachedExamplesRepo = unzipSync(uint8Array)
    console.log('Examples monorepo cached successfully')

    return cachedExamplesRepo
}

// Define workflow sequence - automatically appends next step URI to each workflow
const workflowSequence = [
    {
        uri: ResourceUri.WORKFLOW_SETUP_BEGIN,
        name: 'Event Setup - Begin',
        description: 'Start the event tracking setup process',
        content: workflowBegin,
    },
    {
        uri: ResourceUri.WORKFLOW_SETUP_EDIT,
        name: 'Event Setup - Edit',
        description: 'Edit files to add PostHog event tracking',
        content: workflowEdit,
    },
    {
        uri: ResourceUri.WORKFLOW_SETUP_REVISE,
        name: 'Event Setup - Revise',
        description: 'Review and fix any errors in the implementation',
        content: workflowRevise,
    },
]

/**
 * Registers all PostHog integration resources with the MCP server
 */
export function registerIntegrationResources(server: McpServer, _context: Context) {
    // Fetch examples monorepo at startup
    fetchExamplesMonorepo().catch((error) => {
        console.error('Failed to fetch examples monorepo:', error)
    })

    // Register workflow resources with automatic next step appending
    workflowSequence.forEach((workflow, i) => {
        const nextWorkflow = workflowSequence[i + 1]

        // Append next step URI if there is a next workflow
        const content = nextWorkflow
            ? `${workflow.content}\n\n---\n\n**${WORKFLOW_NEXT_STEP_MESSAGE}** ${nextWorkflow.uri}`
            : workflow.content

        server.registerResource(
            workflow.name,
            workflow.uri,
            {
                mimeType: 'text/markdown',
                description: workflow.description,
            },
            async (uri) => {
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
                        uri: ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                            '{framework}',
                            framework
                        ),
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

            // Get the cached monorepo (or fetch if not yet cached)
            const unzippedRepo = await fetchExamplesMonorepo()
            const subfolderPath = FRAMEWORK_EXAMPLE_PATHS[frameworkStr]

            const markdown = convertSubfolderToMarkdown({
                unzippedRepo,
                subfolderPath,
                frameworkName: frameworkStr,
                repoUrl: EXAMPLES_MONOREPO_URL.replace('/archive/refs/heads/main.zip', ''),
            })

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
