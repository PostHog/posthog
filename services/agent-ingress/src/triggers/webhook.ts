/**
 * Generic webhook trigger. Body is delivered verbatim as the agent's first
 * user message (JSON-stringified). Used for arbitrary integrations.
 *
 * Auth is applied per the agent's `spec.auth`. The principal is captured on
 * the session for later strict-match enforcement.
 */

import { Request, Response, Router } from 'express'
import { z } from 'zod'

import { SessionQueue } from '@posthog/agent-shared'

import { principalDisplay } from '../enqueue/acl'
import { authorize, AuthProvider, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
import { enqueueOrResume } from '../enqueue/enqueue'
import { asyncHandler } from '../routing/http-utils'
import { RevisionResolver } from '../routing/resolver'
import { hasTrigger, resolveAgent } from './resolve'
import type { TriggerModule } from './types'
import { WebhookBodySchema } from './webhook.schemas'

export interface WebhookTriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    teamId: number
    authProvider?: AuthProvider
}

export function webhookRouter(deps: WebhookTriggerDeps): Router {
    const r = Router({ mergeParams: true })
    r.post(
        '/webhook',
        asyncHandler(async (req: Request, res: Response) => {
            const resolved = await resolveAgent(deps.resolver, req, res)
            if (!resolved) {
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            if (!hasTrigger(resolved, 'webhook')) {
                res.status(404).json({ error: 'no_webhook_trigger' })
                return
            }
            const parsed = WebhookBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_body', issues: parsed.error.issues })
                return
            }
            const auth = await authorize(
                req,
                resolved.application,
                resolved.revision.spec,
                deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
            )
            if (!auth.ok) {
                res.status(auth.status).json({ error: auth.reason })
                return
            }
            const externalKeyHeader = req.headers['x-external-key']
            const externalKey = typeof externalKeyHeader === 'string' ? externalKeyHeader : null
            const sessionPrincipal = auth.principal
            const outcome = await enqueueOrResume(
                { queue: deps.queue, teamId: deps.teamId },
                {
                    application: resolved.application,
                    revision: resolved.revision,
                    externalKey,
                    seed: {
                        role: 'user',
                        content: JSON.stringify(parsed.data),
                        timestamp: Date.now(),
                        sender: sessionPrincipal,
                    },
                    principal: sessionPrincipal,
                    trigger: 'webhook',
                    requesterDisplay: principalDisplay(sessionPrincipal),
                }
            )
            if (outcome.kind === 'elevation_required') {
                res.status(403).json({
                    error: 'elevation_required',
                    elevation_request_id: outcome.elevationRequestId,
                    session_id: outcome.sessionId,
                    owner_display: outcome.existingPrincipalDisplay,
                })
                return
            }
            res.json({ ok: true, session_id: outcome.sessionId, resumed: outcome.isResume })
        })
    )
    return r
}

/** The published `bodySchema` is intentionally loose — webhook accepts any
 *  JSON object, and the agent's `agent.md` defines what the *content* of that
 *  object should look like. We do reject null / non-object bodies at the edge
 *  so the seed message isn't `"null"`. */
export const webhookTrigger: TriggerModule = {
    type: 'webhook',
    router: webhookRouter,
    routes: [
        {
            method: 'POST',
            path: '/webhook',
            bodySchema: z.toJSONSchema(WebhookBodySchema),
            auth: 'agent_spec',
        },
    ],
}
