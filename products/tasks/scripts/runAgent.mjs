#!/usr/bin/env node
/**
 * Cloud agent runner script.
 * Runs inside the sandbox container (Docker locally, Modal in production).
 *
 * Usage:
 *   node runAgent.mjs --taskId <id> --runId <id> --repositoryPath <path> [--createPR true]
 *   node runAgent.mjs --prompt "Do something" --repositoryPath <path> [--max-turns 10]
 *
 * Environment variables:
 *   POSTHOG_API_URL - PostHog API URL (required)
 *   POSTHOG_PERSONAL_API_KEY - API key (required)
 *   POSTHOG_PROJECT_ID - Project ID (required for task mode)
 */
import { ClientSideConnection, PROTOCOL_VERSION, ndJsonStream } from '@agentclientprotocol/sdk'

import { Agent } from '@posthog/agent'

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

/**
 * Fetch task details from PostHog API.
 */
async function fetchTask(apiUrl, apiKey, projectId, taskId) {
    const url = `${apiUrl}/api/projects/${projectId}/tasks/${taskId}/`
    const response = await fetch(url, {
        headers: {
            Authorization: `Bearer ${apiKey}`,
            'Content-Type': 'application/json',
        },
    })

    if (!response.ok) {
        throw new Error(`Failed to fetch task: ${response.status} ${response.statusText}`)
    }

    return response.json()
}

/**
 * Create ACP client that handles permission requests automatically (bypass mode for cloud).
 */
function createCloudClient() {
    return {
        async requestPermission(params) {
            // Auto-approve all permissions in cloud mode
            const allowOption = params.options.find((o) => o.kind === 'allow_once' || o.kind === 'allow_always')
            return {
                outcome: {
                    outcome: 'selected',
                    optionId: allowOption?.optionId ?? params.options[0].optionId,
                },
            }
        },
        async sessionUpdate() {
            // Session updates are logged via OTEL
        },
        async extNotification() {
            // Extension notifications are logged via OTEL
        },
    }
}

export async function runAgent({
    taskId,
    runId,
    repositoryPath,
    posthogApiUrl,
    posthogApiKey,
    posthogProjectId,
    prompt,
    maxTurns,
    createPR,
}) {
    const projectId = parseInt(posthogProjectId, 10)

    // Set up environment for Claude Code SDK
    // If ANTHROPIC_API_KEY is set, bypass the LLM gateway and go directly to Anthropic
    // Otherwise, use the LLM gateway with PostHog API key authentication
    const directAnthropicKey = process.env.ANTHROPIC_API_KEY
    const llmGatewayUrl = process.env.LLM_GATEWAY_URL || `${posthogApiUrl}/api/projects/${projectId}/llm_gateway`

    const envOverrides = {
        POSTHOG_API_KEY: posthogApiKey,
        POSTHOG_API_HOST: posthogApiUrl,
        POSTHOG_AUTH_HEADER: `Bearer ${posthogApiKey}`,
        // If direct Anthropic key is set, use it and bypass gateway; otherwise use PostHog key via gateway
        ANTHROPIC_API_KEY: directAnthropicKey || posthogApiKey,
        ANTHROPIC_AUTH_TOKEN: directAnthropicKey || posthogApiKey,
        // If direct Anthropic key is set, point to Anthropic API; otherwise use LLM gateway
        ANTHROPIC_BASE_URL: directAnthropicKey ? 'https://api.anthropic.com' : llmGatewayUrl,
    }
    Object.assign(process.env, envOverrides)

    // Determine the prompt to use
    let taskPrompt = prompt
    let task = null

    if (!taskPrompt && taskId) {
        // Fetch task from API to get description

        task = await fetchTask(posthogApiUrl, posthogApiKey, projectId, taskId)
        taskPrompt = task.description
    }

    if (!taskPrompt) {
        throw new Error('No prompt provided and could not fetch task description')
    }

    // Create agent with OTEL logging enabled
    // Only configure posthog gateway if NOT using direct Anthropic key (to avoid overwriting ANTHROPIC_BASE_URL)
    const agent = new Agent({
        ...(directAnthropicKey
            ? {}
            : {
                  posthog: {
                      apiUrl: posthogApiUrl,
                      getApiKey: () => posthogApiKey,
                      projectId,
                  },
              }),
        otelTransport: {
            host: posthogApiUrl,
            apiKey: posthogApiKey,
            logsPath: '/i/v1/agent-logs',
        },
        debug: true,
    })

    // Get ACP connection from agent
    const acpConnection = await agent.run(taskId || 'cloud-task', runId || `run-${Date.now()}`, {})
    const { clientStreams } = acpConnection

    // Create client-side ACP connection
    const clientStream = ndJsonStream(clientStreams.writable, clientStreams.readable)
    const connection = new ClientSideConnection(() => createCloudClient(), clientStream)

    // Initialize the connection
    await connection.initialize({
        protocolVersion: PROTOCOL_VERSION,
        clientCapabilities: {
            fs: { readTextFile: true, writeTextFile: true },
            terminal: true,
        },
    })

    // Create a new session
    const sessionId = runId || `session-${Date.now()}`
    const sessionMeta = {
        sessionId,
        ...(maxTurns && {
            claudeCode: {
                options: {
                    maxTurns: parseInt(maxTurns, 10),
                },
            },
        }),
    }

    await connection.newSession({
        cwd: repositoryPath,
        mcpServers: [],
        _meta: sessionMeta,
    })

    // Send the prompt and wait for completion
    let result
    try {
        result = await connection.prompt({
            sessionId,
            prompt: [{ type: 'text', text: taskPrompt }],
        })

        // Handle PR creation if requested and task completed successfully
        if (createPR && result.stopReason === 'end_turn') {
        }
    } finally {
        // Always flush logs and clean up, even if prompt execution fails
        await agent.flushAllLogs().catch((err) => console.error('Failed to flush logs:', err))
        await acpConnection.cleanup().catch((err) => console.error('Failed to cleanup:', err))
    }

    return result
}

async function main() {
    const { taskId, runId, repositoryPath, prompt, 'max-turns': maxTurns, createPR } = parseArgs()

    if (!prompt && !taskId) {
        console.error('Missing required argument: either --prompt or --taskId must be provided')
        process.exit(1)
    }

    if (taskId && !runId) {
        console.error('Missing required argument: --runId (required when using --taskId)')
        process.exit(1)
    }

    if (!repositoryPath) {
        console.error('Missing required argument: --repositoryPath')
        process.exit(1)
    }

    const posthogApiUrl = process.env.POSTHOG_API_URL
    const posthogApiKey = process.env.POSTHOG_PERSONAL_API_KEY
    const posthogProjectId = process.env.POSTHOG_PROJECT_ID

    if (!posthogApiUrl) {
        console.error('Missing required environment variable: POSTHOG_API_URL')
        process.exit(1)
    }

    if (!posthogApiKey) {
        console.error('Missing required environment variable: POSTHOG_PERSONAL_API_KEY')
        process.exit(1)
    }

    if (taskId && !posthogProjectId) {
        console.error('Missing required environment variable: POSTHOG_PROJECT_ID')
        process.exit(1)
    }

    try {
        await runAgent({
            taskId,
            runId,
            repositoryPath,
            posthogApiUrl,
            posthogApiKey,
            posthogProjectId,
            prompt,
            maxTurns,
            createPR: createPR === 'true',
        })
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
