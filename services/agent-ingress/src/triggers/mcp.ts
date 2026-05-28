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
import { z } from 'zod'

import { SessionQueue } from '@posthog/agent-shared'
import { SessionEventBus } from '@posthog/agent-shared'

import { enqueueOrResume } from '../enqueue/enqueue'
import { asyncHandler } from '../routing/http-utils'
import { RevisionResolver } from '../routing/resolver'
import { McpRequestBodySchema, McpStreamQuerySchema } from './mcp.schemas'
import { resolveAgent } from './resolve'
import type { TriggerModule } from './types'

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

    r.post(
        '/mcp',
        asyncHandler(async (req: Request, res: Response) => {
            const parsed = McpRequestBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_body', issues: parsed.error.issues })
                return
            }
            const resolved = await resolveAgent(deps.resolver, req, res)
            if (!resolved) {
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            const body = parsed.data as McpRequest
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
    )

    r.get(
        '/mcp/stream',
        asyncHandler(async (req: Request, res: Response) => {
            const parsed = McpStreamQuerySchema.safeParse(req.query)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_query', issues: parsed.error.issues })
                return
            }
            const { session_id: sessionId } = parsed.data
            res.setHeader('Content-Type', 'text/event-stream')
            res.setHeader('Cache-Control', 'no-cache')
            res.flushHeaders()
            const unsubscribe = deps.bus.subscribe(sessionId, (event) => {
                res.write(`event: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`)
            })
            req.on('close', () => unsubscribe())
        })
    )

    return r
}

/** Body is JSON-RPC 2.0 per the MCP transport spec. The `bodySchema` advertises
 *  the envelope; `params` shape depends on the method and is documented in the
 *  MCP spec (modelcontextprotocol.io). */
export const mcpTrigger: TriggerModule = {
    type: 'mcp',
    router: mcpRouter,
    routes: [
        {
            method: 'POST',
            path: '/mcp',
            bodySchema: z.toJSONSchema(McpRequestBodySchema),
            auth: 'agent_spec',
        },
        {
            method: 'GET',
            path: '/mcp/stream',
            querySchema: z.toJSONSchema(McpStreamQuerySchema),
            auth: 'agent_spec',
        },
    ],
}
