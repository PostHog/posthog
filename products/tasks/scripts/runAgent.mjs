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

export async function runAgent(
    taskId,
    repositoryPath,
    posthogApiUrl,
    posthogApiKey,
    posthogProjectId,
    prompt,
    maxTurns
) {
    const envOverrides = {
        POSTHOG_API_KEY: posthogApiKey,
        POSTHOG_API_HOST: posthogApiUrl,
        POSTHOG_AUTH_HEADER: `Bearer ${posthogApiKey}`,
        ANTHROPIC_API_KEY: posthogApiKey,
        ANTHROPIC_AUTH_TOKEN: posthogApiKey,
        ANTHROPIC_BASE_URL: `${posthogApiUrl}/api/projects/${posthogProjectId}/llm_gateway`,
    }

    const agent = new Agent({
        workingDirectory: repositoryPath,
        posthogApiUrl,
        posthogApiKey,
        debug: true,
        onEvent: (event) => {
            if (event.type !== 'token') {
                console.info(JSON.stringify({ type: 'event', data: event }))
            }
        },
    })

    if (prompt) {
        const options = {
            repositoryPath,
            permissionMode: PermissionMode.BYPASS,
            isCloudMode: true,
        }

        if (maxTurns) {
            options.queryOverrides = {
                maxTurns: parseInt(maxTurns, 10),
            }
        }

        await agent.run(prompt, options)
    } else {
        await agent.runTask(taskId, {
            repositoryPath,
            permissionMode: PermissionMode.BYPASS,
            isCloudMode: true,
            createPR: true,
            autoProgress: true,
            queryOverrides: {
                env: envOverrides,
            },
        })
    }
}

async function main() {
    const { taskId, repositoryPath, prompt, 'max-turns': maxTurns } = parseArgs()

    if (!prompt && !taskId) {
        console.error('Missing required argument: either --prompt or --taskId must be provided')
        process.exit(1)
    }

    if (!prompt && !taskId) {
        console.error('Missing required argument: taskId (required when using taskId)')
        process.exit(1)
    }

    if (!repositoryPath) {
        console.error('Missing required argument: repositoryPath')
        process.exit(1)
    }

    const posthogApiUrl = process.env.POSTHOG_API_URL
    const posthogApiKey = process.env.POSTHOG_PERSONAL_API_KEY
    const posthogProjectId = process.env.POSTHOG_PROJECT_ID

    if (!posthogApiUrl) {
        console.error('Missing required environment variables: POSTHOG_API_URL')
        process.exit(1)
    }

    if (!posthogApiKey) {
        console.error('Missing required environment variables: POSTHOG_PERSONAL_API_KEY')
        process.exit(1)
    }

    if (!prompt && !posthogProjectId) {
        console.error('Missing required environment variables: POSTHOG_PROJECT_ID')
        process.exit(1)
    }

    try {
        await runAgent(taskId, repositoryPath, posthogApiUrl, posthogApiKey, posthogProjectId, prompt, maxTurns)
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
