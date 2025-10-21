import type { Context } from '@/tools/types'
import type { Prompt } from './index'
import { ResourceUri } from '@/resources'

export async function setupEventsPrompt(_context: Context): Promise<Prompt> {
    return {
        name: 'posthog-setup',
        title: 'Setup a deep PostHog integration',
        description:
            'Automatically instrument your Next.js project with PostHog event tracking, user identification, and error tracking',
        handler: async (_context, _args) => {
            return {
                messages: [
                    {
                        role: 'user',
                        content: {
                            type: 'text',
                            text: `Setup automatic PostHog event tracking in this project.

Use these MCP resources:
- ${ResourceUri.WORKFLOW_SETUP_BEGIN} - The event setup workflow guide (start here)
- ${ResourceUri.DOCS_FRAMEWORK} - Integration documentation per framework
- ${ResourceUri.EXAMPLE_PROJECT_FRAMEWORK} - Example project with a known-good PostHog integration

Follow the workflow guide to implement a deep PostHog integration.`,
                        },
                    },
                    {
                        role: 'assistant',
                        content: {
                            type: 'text',
                            text: "I'll set up PostHog event tracking in your project using the provided workflow guide and documentation.",
                        },
                    },
                ],
            }
        },
    }
}
