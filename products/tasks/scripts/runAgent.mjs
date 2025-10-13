#!/usr/bin/env node
import { Agent, PermissionMode } from '@posthog/agent'

function parseArgs() {
    const args = process.argv.slice(2)
    const parsed = {}

    for (let i = 0; i < args.length; i += 2) {
        const key = args[i].replace(/^--/, '')
        const value = args[i + 1]
        parsed[key] = value
    }

    return parsed
}

export async function runAgent(taskId, workflowId, repositoryPath, posthogApiUrl, posthogApiKey) {
    const agent = new Agent({
        workingDirectory: repositoryPath,
        posthogApiUrl,
        posthogApiKey,
        onEvent: (event) => {
            if (event.type !== 'token') {
                console.info(JSON.stringify({ type: 'event', data: event }))
            }
        },
    })

    await agent.runWorkflow(taskId, workflowId, {
        repositoryPath,
        permissionMode: PermissionMode.ACCEPT_EDITS,
        autoProgress: true,
    })
}

async function main() {
    const { taskId, workflowId, repositoryPath } = parseArgs()

    if (!taskId) {
        console.error('Missing required argument: taskId')
        process.exit(1)
    }

    if (!workflowId) {
        console.error('Missing required argument: workflowId')
        process.exit(1)
    }

    if (!repositoryPath) {
        console.error('Missing required argument: repositoryPath')
        process.exit(1)
    }

    const posthogApiUrl = process.env.POSTHOG_API_URL
    const posthogApiKey = process.env.POSTHOG_PERSONAL_API_KEY

    if (!posthogApiUrl) {
        console.error('Missing required environment variables: POSTHOG_API_URL')
        process.exit(1)
    }

    if (!posthogApiKey) {
        console.error('Missing required environment variables: POSTHOG_PERSONAL_API_KEY')
        process.exit(1)
    }

    try {
        await runAgent(taskId, workflowId, repositoryPath, posthogApiUrl, posthogApiKey)
        process.exit(0)
    } catch (error) {
        console.error(
            JSON.stringify({
                type: 'error',
                message: error instanceof Error ? error.message : String(error),
                stack: error instanceof Error ? error.stack : undefined,
            })
        )
        process.exit(1)
    }
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main()
}
