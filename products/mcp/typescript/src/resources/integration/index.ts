import { type McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Context } from '@/tools/types'
import {
    FRAMEWORK_DOCS,
    FRAMEWORK_EXAMPLES,
    isSupportedFramework,
    getSupportedFrameworks,
    getSupportedFrameworksList,
} from './framework-mappings'
import { convertRepoToMarkdown } from './repo-to-md'

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

// Define workflow sequence - automatically appends next step URI to each workflow
const workflowSequence = [
    {
        uri: ResourceUri.WORKFLOW_SETUP_BEGIN,
        name: 'PostHog Setup - Begin',
        description: 'Start the event tracking setup process',
        content: workflowBegin,
    },
    {
        uri: ResourceUri.WORKFLOW_SETUP_EDIT,
        name: 'PostHog Setup - Edit',
        description: 'Edit files to add PostHog event tracking',
        content: workflowEdit,
    },
    {
        uri: ResourceUri.WORKFLOW_SETUP_REVISE,
        name: 'PostHog Setup - Revise',
        description: 'Review and fix any errors in the implementation',
        content: workflowRevise,
    },
]

/**
 * Registers all PostHog integration resources with the MCP server
 */
export function registerIntegrationResources(server: McpServer, _context: Context) {
    // Register workflow resources with automatic next step appending
    workflowSequence.forEach((workflow, i) => {
        const nextWorkflow = workflowSequence[i + 1]

        // Append next step URI if there is a next workflow
        const content = nextWorkflow
            ? `${workflow.content}\n\n---\n\n**Upon completion, access the following resource to continue:** ${nextWorkflow.uri}`
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
                // Return a resource entry for each supported framework
                const frameworks = getSupportedFrameworks()
                return {
                    resources: frameworks.map((framework: string) => ({
                        uri: ResourceUri.DOCS_FRAMEWORK.replace('{framework}', framework),
                        name: `PostHog ${framework} Integration Docs`,
                        description: `PostHog integration documentation for ${framework}`,
                        mimeType: 'text/markdown',
                    })),
                }
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
                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: `Framework "${frameworkStr || 'unknown'}" is not supported yet. Currently supported: ${getSupportedFrameworksList()}`,
                        },
                    ],
                }
            }

            const docsUrl = FRAMEWORK_DOCS[frameworkStr]
            const response = await fetch(docsUrl)
            const content = await response.text()
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
            const response = await fetch(
                'https://posthog.com/docs/getting-started/identify-users.md'
            )
            const content = await response.text()
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
                // Return a resource entry for each supported framework
                const frameworks = getSupportedFrameworks()
                return {
                    resources: frameworks.map((framework: string) => ({
                        uri: ResourceUri.EXAMPLE_PROJECT_FRAMEWORK.replace(
                            '{framework}',
                            framework
                        ),
                        name: `PostHog ${framework} Example Project`,
                        description: `Example project showing PostHog integration with ${framework}`,
                        mimeType: 'text/markdown',
                    })),
                }
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
                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: `Framework "${frameworkStr || 'unknown'}" is not supported yet. Currently supported: ${getSupportedFrameworksList()}`,
                        },
                    ],
                }
            }

            try {
                const zipUrl = FRAMEWORK_EXAMPLES[frameworkStr]
                const markdown = await convertRepoToMarkdown({
                    zipUrl,
                    frameworkName: frameworkStr,
                })

                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: markdown,
                        },
                    ],
                }
            } catch (error) {
                return {
                    contents: [
                        {
                            uri: uri.toString(),
                            text: `Error loading example project: ${error}\n\nPlease check your network connection and try again.`,
                        },
                    ],
                }
            }
        }
    )
}
