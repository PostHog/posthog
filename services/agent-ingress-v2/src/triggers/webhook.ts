/**
 * Generic webhook trigger. Body is delivered verbatim as the agent's first
 * user message (JSON-stringified). Used for arbitrary integrations.
 */

import { Request, Response, Router } from 'express'

import { SessionQueue } from '@posthog/agent-shared-v2'

import { enqueueOrResume } from '../enqueue'
import { RevisionResolver } from '../resolver'
import { hasTrigger, resolveAgent } from './resolve'

export interface WebhookTriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    teamId: number
}

export function webhookRouter(deps: WebhookTriggerDeps): Router {
    const r = Router({ mergeParams: true })
    r.post('/webhook', async (req: Request, res: Response) => {
        const resolved = await resolveAgent(deps.resolver, req)
        if (!resolved) {
            res.status(404).json({ error: 'no_agent' })
            return
        }
        if (!hasTrigger(resolved, 'webhook')) {
            res.status(404).json({ error: 'no_webhook_trigger' })
            return
        }
        const externalKeyHeader = req.headers['x-external-key']
        const externalKey = typeof externalKeyHeader === 'string' ? externalKeyHeader : null
        const { sessionId, isResume } = await enqueueOrResume(
            { queue: deps.queue, teamId: deps.teamId },
            {
                application: resolved.application,
                revision: resolved.revision,
                externalKey,
                seed: { role: 'user', content: JSON.stringify(req.body) },
            }
        )
        res.json({ ok: true, session_id: sessionId, resumed: isResume })
    })
    return r
}
