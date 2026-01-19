#!/usr/bin/env node
/**
 * Agent Server for Cloud Sessions
 *
 * This script runs in the sandbox and:
 * 1. Creates an ACP connection with proper streaming
 * 2. Subscribes to Redis channel for user messages (cloud-session:{runId}:to-agent)
 * 3. Bridges ACP streams to Redis pub/sub (cloud-session:{runId}:from-agent)
 * 4. Persists all events to S3 via append_log API
 */

import {
    Agent,
    createAcpConnection,
    FileSyncManager,
    PostHogAPIClient,
    SessionStore,
    Logger,
    getLlmGatewayUrl,
} from '@posthog/agent'
import { ClientSideConnection, ndJsonStream, PROTOCOL_VERSION } from '@agentclientprotocol/sdk'
import Redis from 'ioredis'

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

class AgentServer {
    constructor(config) {
        this.config = config
        this.isRunning = false
        this.subscriber = null
        this.publisher = null
        this.toAgentChannel = `cloud-session:${config.runId}:to-agent`
        this.fromAgentChannel = `cloud-session:${config.runId}:from-agent`
        this.toAgentQueue = `cloud-session:${config.runId}:to-agent:queue`
        this.logger = new Logger({ debug: true, prefix: '[AgentServer]' })
        this.acpConnection = null
        this.clientConnection = null
        this.fileSyncManager = null
        this.apiClient = null
        this.sessionStore = null
        this.eventCounter = 0
        this.lastHeartbeatTime = 0
    }

    async connect() {
        this.logger.info(`Connecting to Redis: ${this.config.redisUrl}`)
        this.logger.info(`Subscribing to channel: ${this.toAgentChannel}`)

        this.subscriber = new Redis(this.config.redisUrl)
        this.publisher = new Redis(this.config.redisUrl)

        this.subscriber.on('error', (error) => {
            this.logger.error('Redis subscriber error:', error.message)
        })

        this.publisher.on('error', (error) => {
            this.logger.error('Redis publisher error:', error.message)
        })

        await this.subscriber.subscribe(this.toAgentChannel)
        this.logger.info('Redis subscription established')

        this.subscriber.on('message', async (channel, message) => {
            this.logger.info(`[REDIS] Received message on channel: ${channel}`)
            this.logger.debug(`[REDIS] Raw message: ${message}`)
            if (channel === this.toAgentChannel) {
                try {
                    const parsed = JSON.parse(message)
                    this.logger.info(`[REDIS] Parsed message method: ${parsed.method}`)
                    await this.handleMessage(parsed)
                } catch (error) {
                    this.logger.warn('Failed to parse Redis message:', message, error)
                }
            } else {
                this.logger.warn(`[REDIS] Unexpected channel: ${channel}`)
            }
        })

        this.isRunning = true

        // Send connected status
        await this.sendStatusNotification('connected', 'Agent server connected')
    }

    async sendStatusNotification(status, message) {
        const notification = {
            type: 'notification',
            timestamp: new Date().toISOString(),
            notification: {
                jsonrpc: '2.0',
                method: 'session/update',
                params: {
                    sessionId: this.config.runId,
                    update: {
                        sessionUpdate: 'agent_message_chunk',
                        content: {
                            type: 'text',
                            text: `[${status}] ${message}`,
                        },
                    },
                },
            },
        }
        await this.sendEvent(notification)
    }

    async sendEvent(event) {
        this.logger.info(`[SEND_EVENT] Sending event: method=${event.notification?.method || event.method || 'unknown'}`)
        this.logger.debug(`[SEND_EVENT] Full event:`, JSON.stringify(event, null, 2))

        // Send throttled heartbeat to keep session alive during long tasks
        this.maybeHeartbeat()

        // Persist to S3 first (source of truth)
        try {
            await this.persistEvent(event)
            this.logger.info(`[SEND_EVENT] Persisted to S3 successfully`)
        } catch (error) {
            this.logger.error('[SEND_EVENT] Failed to persist event to S3:', error.message)
        }

        // Then publish to Redis (real-time)
        try {
            // Send the notification content for SSE
            const ssePayload = event.notification || event
            this.logger.info(`[SEND_EVENT] Publishing to Redis channel: ${this.fromAgentChannel}`)
            this.logger.debug(`[SEND_EVENT] SSE payload:`, JSON.stringify(ssePayload, null, 2))
            const result = await this.publisher.publish(this.fromAgentChannel, JSON.stringify(ssePayload))
            this.logger.info(`[SEND_EVENT] Redis publish result (subscribers): ${result}`)
        } catch (error) {
            this.logger.error('[SEND_EVENT] Failed to publish event to Redis:', error.message)
        }
    }

    maybeHeartbeat() {
        const now = Date.now()
        const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000 // 5 minutes

        if (now - this.lastHeartbeatTime > HEARTBEAT_INTERVAL_MS) {
            this.lastHeartbeatTime = now
            this.sendHeartbeat().catch((err) => {
                this.logger.warn('Failed to send heartbeat:', err.message)
            })
        }
    }

    async sendHeartbeat() {
        const { apiUrl, apiKey, projectId, taskId, runId } = this.config
        const url = `${apiUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/heartbeat`

        const response = await fetch(url, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${apiKey}`,
                'Content-Type': 'application/json',
            },
        })

        if (!response.ok) {
            throw new Error(`Heartbeat failed: ${response.status}`)
        }

        this.logger.info('Heartbeat sent successfully')
    }

    async persistEvent(event) {
        const { apiUrl, apiKey, projectId, taskId, runId } = this.config
        const url = `${apiUrl}/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/append_log`

        const response = await fetch(url, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${apiKey}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                entries: [event],
            }),
        })

        if (!response.ok) {
            throw new Error(`Failed to persist: ${response.status}`)
        }
    }

    async handleMessage(message) {
        const method = message.method
        this.logger.info(`Received message: ${method}`)

        switch (method) {
            case '_posthog/user_message':
                await this.handleUserMessage(message.params)
                break
            case '_posthog/cancel':
                await this.handleCancel()
                break
            case '_posthog/close':
                await this.handleClose()
                break
            default:
                this.logger.info(`Unknown method: ${method}`)
        }
    }

    async handleUserMessage(params) {
        const content = params.content
        this.logger.info(`[USER_MSG] Processing user message: ${content.substring(0, 100)}...`)

        // Ensure we have an ACP connection
        if (!this.clientConnection) {
            this.logger.info(`[USER_MSG] No ACP connection, initializing...`)
            await this.initializeAcpConnection()
        }

        try {
            this.logger.info(`[USER_MSG] Sending prompt via ACP protocol`)
            // Send prompt via ACP protocol
            const result = await this.clientConnection.prompt({
                sessionId: this.config.runId,
                prompt: [{ type: 'text', text: content }],
            })

            this.logger.info(`[USER_MSG] Prompt completed with stopReason: ${result.stopReason}`)
        } catch (error) {
            this.logger.error('[USER_MSG] Agent error:', error)
            await this.sendStatusNotification('error', error.message)
        }
    }

    async initializeAcpConnection() {
        this.logger.info('Initializing ACP connection')

        // Set up environment for LLM gateway
        // Prefer explicit LLM_GATEWAY_URL env var (needed for Docker where localhost doesn't work)
        const gatewayUrl = process.env.LLM_GATEWAY_URL || getLlmGatewayUrl(this.config.apiUrl)
        this.logger.info(`Using LLM gateway URL: ${gatewayUrl}`)

        const envOverrides = {
            POSTHOG_API_KEY: this.config.apiKey,
            POSTHOG_API_HOST: this.config.apiUrl,
            POSTHOG_AUTH_HEADER: `Bearer ${this.config.apiKey}`,
            ANTHROPIC_API_KEY: this.config.apiKey,
            ANTHROPIC_AUTH_TOKEN: this.config.apiKey,
            ANTHROPIC_BASE_URL: gatewayUrl,
        }
        Object.assign(process.env, envOverrides)

        // Create API client and session store
        this.apiClient = new PostHogAPIClient({
            apiUrl: this.config.apiUrl,
            getApiKey: () => this.config.apiKey,
            projectId: this.config.projectId,
        })

        this.sessionStore = new SessionStore(
            this.apiClient,
            new Logger({ debug: true, prefix: '[SessionStore]' })
        )

        // Create FileSyncManager
        this.fileSyncManager = new FileSyncManager({
            workingDirectory: this.config.repositoryPath,
            taskId: this.config.taskId,
            runId: this.config.runId,
            apiClient: this.apiClient,
        })

        // Create ACP connection with session store for persistence
        this.acpConnection = createAcpConnection({
            sessionStore: this.sessionStore,
            sessionId: this.config.runId,
            taskId: this.config.taskId,
        })

        // Register session in store
        this.sessionStore.register(this.config.runId, {
            taskId: this.config.taskId,
            runId: this.config.runId,
            logUrl: '',
        })

        // Create client connection using the client-side streams
        const clientStream = ndJsonStream(
            this.acpConnection.clientStreams.writable,
            this.acpConnection.clientStreams.readable
        )

        // Note: We forward events to Redis via the sessionUpdate callback below,
        // not by tapping the stream (which would require locking it twice)
        const self = this

        // Create client that auto-approves permissions and forwards events
        const cloudClient = {
            async requestPermission(params) {
                // Auto-approve all permissions in cloud mode
                const allowOption = params.options.find(
                    (o) => o.kind === 'allow_once' || o.kind === 'allow_always'
                )
                return {
                    outcome: {
                        outcome: 'selected',
                        optionId: allowOption?.optionId ?? params.options[0].optionId,
                    },
                }
            },
            async sessionUpdate(params) {
                self.logger.info(`[SESSION_UPDATE] Received sessionUpdate: ${params.update?.sessionUpdate || 'unknown'}`)
                self.logger.debug(`[SESSION_UPDATE] Full params:`, JSON.stringify(params, null, 2))

                // Normalize sessionId to use our runId (ACP SDK generates its own session IDs)
                const normalizedParams = {
                    ...params,
                    sessionId: self.config.runId,
                }

                // Forward session updates to Redis for real-time streaming
                const notification = {
                    type: 'notification',
                    timestamp: new Date().toISOString(),
                    notification: {
                        jsonrpc: '2.0',
                        method: 'session/update',
                        params: normalizedParams,
                    },
                }
                await self.sendEvent(notification)

                // Handle file sync events
                if (params.update?.sessionUpdate === 'tool_result') {
                    const toolName = params.update?.toolName
                    const result = params.update?.result
                    if (toolName === 'Write' || toolName === 'Edit') {
                        const filePath = result?.file_path || result?.filePath
                        if (filePath) {
                            await self.handleFileChange(
                                filePath,
                                toolName === 'Write' ? 'file_created' : 'file_modified'
                            )
                        }
                    }
                }
            },
        }

        this.clientConnection = new ClientSideConnection((_agent) => cloudClient, clientStream)

        // Initialize the connection
        await this.clientConnection.initialize({
            protocolVersion: PROTOCOL_VERSION,
            clientCapabilities: {},
        })

        // Create new session
        await this.clientConnection.newSession({
            cwd: this.config.repositoryPath,
            mcpServers: [],
            _meta: { sessionId: this.config.runId },
        })

        this.logger.info('ACP connection initialized')
    }

    async handleFileChange(filePath, eventType) {
        if (!this.fileSyncManager) {
            this.logger.warn('FileSyncManager not initialized')
            return
        }

        try {
            let event
            if (eventType === 'file_created') {
                event = await this.fileSyncManager.onFileCreated(filePath)
            } else {
                event = await this.fileSyncManager.onFileWritten(filePath)
            }

            if (event) {
                this.logger.info(`File synced: ${event.relativePath}`)
                await this.sendFileSyncEvent(event)
            }
        } catch (error) {
            this.logger.error('Failed to sync file:', filePath, error)
        }
    }

    async sendFileSyncEvent(event) {
        const notification = {
            type: 'notification',
            timestamp: new Date().toISOString(),
            notification: {
                jsonrpc: '2.0',
                method: '_posthog/file_sync',
                params: event,
            },
        }
        await this.sendEvent(notification)
    }

    async handleCancel() {
        this.logger.info('Cancel requested')
        if (this.clientConnection) {
            try {
                await this.clientConnection.cancel({ sessionId: this.config.runId })
            } catch (error) {
                this.logger.error('Failed to cancel:', error)
            }
        }
    }

    async handleClose() {
        this.logger.info('Close requested')
        await this.stop()
    }

    async start() {
        this.isRunning = true
        await this.connect()

        // Initialize ACP connection immediately so we're ready for prompts
        await this.initializeAcpConnection()

        await new Promise((resolve) => {
            const checkRunning = () => {
                if (!this.isRunning) {
                    resolve()
                } else {
                    setTimeout(checkRunning, 1000)
                }
            }
            checkRunning()
        })
    }

    async stop() {
        this.isRunning = false

        // Clean up ACP connection
        if (this.acpConnection) {
            await this.acpConnection.cleanup()
        }

        if (this.subscriber) {
            await this.subscriber.unsubscribe(this.toAgentChannel)
            await this.subscriber.quit()
        }

        if (this.publisher) {
            await this.publisher.quit()
        }
    }
}

async function main() {
    const { taskId, runId, repositoryPath } = parseArgs()

    if (!taskId) {
        console.error('Missing required argument: --taskId')
        process.exit(1)
    }

    if (!runId) {
        console.error('Missing required argument: --runId')
        process.exit(1)
    }

    if (!repositoryPath) {
        console.error('Missing required argument: --repositoryPath')
        process.exit(1)
    }

    const redisUrl = process.env.REDIS_URL
    const apiUrl = process.env.POSTHOG_API_URL
    const apiKey = process.env.POSTHOG_PERSONAL_API_KEY
    const projectId = process.env.POSTHOG_PROJECT_ID

    if (!redisUrl) {
        console.error('Missing required environment variable: REDIS_URL')
        process.exit(1)
    }

    if (!apiUrl) {
        console.error('Missing required environment variable: POSTHOG_API_URL')
        process.exit(1)
    }

    if (!apiKey) {
        console.error('Missing required environment variable: POSTHOG_PERSONAL_API_KEY')
        process.exit(1)
    }

    if (!projectId) {
        console.error('Missing required environment variable: POSTHOG_PROJECT_ID')
        process.exit(1)
    }

    const server = new AgentServer({
        redisUrl,
        apiUrl,
        apiKey,
        projectId: parseInt(projectId, 10),
        taskId,
        runId,
        repositoryPath,
    })

    process.on('SIGINT', async () => {
        console.log('Received SIGINT, shutting down...')
        await server.stop()
        process.exit(0)
    })

    process.on('SIGTERM', async () => {
        console.log('Received SIGTERM, shutting down...')
        await server.stop()
        process.exit(0)
    })

    try {
        await server.start()
    } catch (error) {
        console.error('Agent server error:', error)
        process.exit(1)
    }
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main()
}
