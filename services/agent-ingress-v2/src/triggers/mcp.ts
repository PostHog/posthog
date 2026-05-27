/**
 * Per-agent MCP transport. Each deployed agent exposes its own streamable
 * MCP endpoint at /agents/<slug>/mcp.
 *
 * Implementation: simple HTTP-streamable variant. Initialize creates or
 * resumes a session (keyed by client-supplied id or generated). The client
 * POSTs JSON-RPC messages; the server replies inline plus streams session
 * events back via SSE on /agents/<slug>/mcp/stream?session_id=...
 *
 * This is the bridge that makes "agent A calling agent B" work — agent B is
 * just an MCP server that A connects to via its slug.
 */

import { Request, Response, Router } from 'express'

import { SessionQueue } from '@posthog/agent-shared-v2'

import { SessionEventBus } from '../bus'
import { enqueueOrResume } from '../enqueue'
import { RevisionResolver } from '../resolver'
import { resolveAgent } from './resolve'

export interface McpTriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    bus: SessionEventBus
    teamId: number
}

interface McpRequest {
    jsonrpc: '2.0'
    id?: number | string
    method: string
    params?: Record<string, unknown>
}

interface McpResponse {
    jsonrpc: '2.0'
    id: number | string | null
    result?: unknown
    error?: { code: number; message: string }
}

export function mcpRouter(deps: McpTriggerDeps): Router {
    const r = Router({ mergeParams: true })

    r.post('/mcp', async (req: Request, res: Response) => {
        const resolved = await resolveAgent(deps.resolver, req)
        if (!resolved) {
            res.status(404).json({ error: 'no_agent' })
            return
        }
        const body = req.body as McpRequest
        const id = body.id ?? null
        const reply = (result: unknown): McpResponse => ({ jsonrpc: '2.0', id, result })
        const errReply = (code: number, message: string): McpResponse => ({
            jsonrpc: '2.0',
            id,
            error: { code, message },
        })

        switch (body.method) {
            case 'initialize': {
                res.json(
                    reply({
                        protocolVersion: '2024-11-05',
                        capabilities: { tools: {}, resources: {} },
                        serverInfo: {
                            name: `agent:${resolved.application.slug}`,
                            version: resolved.revision.id,
                        },
                    })
                )
                return
            }
            case 'tools/list': {
                // The per-agent MCP exposes exactly one tool: "chat" — sending a
                // message to the agent. Callers wishing to use agent-as-tool drop
                // it in their own spec.mcps and we transparently wire it.
                res.json(
                    reply({
                        tools: [
                            {
                                name: 'chat',
                                description: `Send a message to the ${resolved.application.slug} agent.`,
                                inputSchema: {
                                    type: 'object',
                                    properties: {
                                        message: { type: 'string' },
                                        external_key: { type: 'string' },
                                    },
                                    required: ['message'],
                                },
                            },
                        ],
                    })
                )
                return
            }
            case 'tools/call': {
                const params = body.params as { name: string; arguments: Record<string, unknown> } | undefined
                if (!params || params.name !== 'chat') {
                    res.json(errReply(-32601, 'unknown tool'))
                    return
                }
                const message = String(params.arguments.message ?? '')
                const externalKey =
                    typeof params.arguments.external_key === 'string' ? params.arguments.external_key : null
                const { sessionId } = await enqueueOrResume(
                    { queue: deps.queue, teamId: deps.teamId },
                    {
                        application: resolved.application,
                        revision: resolved.revision,
                        externalKey,
                        seed: { role: 'user', content: message, timestamp: Date.now() },
                    }
                )
                res.json(
                    reply({
                        content: [
                            {
                                type: 'text',
                                text: JSON.stringify({ session_id: sessionId, status: 'queued' }),
                            },
                        ],
                    })
                )
                return
            }
            default:
                res.json(errReply(-32601, `unknown method: ${body.method}`))
        }
    })

    r.get('/mcp/stream', async (req: Request, res: Response) => {
        const sessionId = String(req.query.session_id ?? '')
        if (!sessionId) {
            res.status(400).end()
            return
        }
        res.setHeader('Content-Type', 'text/event-stream')
        res.setHeader('Cache-Control', 'no-cache')
        res.flushHeaders()
        const unsubscribe = deps.bus.subscribe(sessionId, (event) => {
            res.write(`event: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`)
        })
        req.on('close', () => unsubscribe())
    })

    return r
}
