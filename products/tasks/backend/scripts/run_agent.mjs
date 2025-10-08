#!/usr/bin/env node
import { Agent, PermissionMode } from '@posthog/agent'

const args = process.argv.slice(2)

function parseArgs() {
    const parsed = {}
    for (let i = 0; i < args.length; i += 2) {
        const key = args[i].replace(/^--/, '')
        const value = args[i + 1]
        parsed[key] = value
    }
    return parsed
}

const { taskId, workflowId, repositoryPath } = parseArgs()

if (!taskId || !workflowId || !repositoryPath) {
    console.error('Missing required arguments: taskId, workflowId, repositoryPath')
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

;(async () => {
    try {
        await agent.runWorkflow(taskId, workflowId, {
            repositoryPath,
            permissionMode: PermissionMode.ACCEPT_EDITS,
            autoProgress: true,
        })

        process.exit(0)
    } catch (error) {
        console.error(
            JSON.stringify({
                type: 'error',
                message: error.messtage,
                stack: error.stack,
            })
        )
        process.exit(1)
    }
})()
