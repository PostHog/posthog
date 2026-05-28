/**
 * Slack events trigger.
 *
 * Expects POST /agents/<slug>/slack/events with Slack's events-api payload.
 * Verifies the signing secret (X-Slack-Signature) when configured, then
 * enqueues an AgentSession using thread_ts as the externalKey so repeated
 * messages in the same thread resume a single agent session.
 */

import { createHmac, timingSafeEqual } from 'crypto'
import { Request, Response, Router } from 'express'

import { IdentityStore, SessionQueue } from '@posthog/agent-shared'

import { enqueueOrResume } from '../enqueue/enqueue'
import { RevisionResolver } from '../routing/resolver'
import { hasTrigger, resolveAgent } from './resolve'

export interface SlackTriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    teamId: number
    signingSecret?: string
    /** Optional identity store — when present, slack events resolve to a stable AgentUser. */
    identities?: IdentityStore
}

export function slackRouter(deps: SlackTriggerDeps): Router {
    const r = Router({ mergeParams: true })
    r.post('/slack/events', async (req: Request, res: Response) => {
        if (deps.signingSecret && !verifySlackSignature(req, deps.signingSecret)) {
            res.status(401).json({ error: 'invalid_signature' })
            return
        }
        const body = req.body as { type?: string; challenge?: string; event?: SlackEvent }
        if (body.type === 'url_verification') {
            res.json({ challenge: body.challenge })
            return
        }
        const event = body.event
        if (!event || event.type !== 'message' || event.bot_id) {
            res.json({ ok: true })
            return
        }
        const resolved = await resolveAgent(deps.resolver, req)
        if (!resolved) {
            res.status(404).json({ error: 'no_agent' })
            return
        }
        if (!hasTrigger(resolved, 'slack')) {
            res.status(404).json({ error: 'no_slack_trigger' })
            return
        }

        // Workspace trust check. trusted_workspaces is required in the spec:
        // an array gates on membership; `"*"` opens to any workspace.
        const slackTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'slack')
        const trusted =
            slackTrigger && 'config' in slackTrigger
                ? (slackTrigger.config as { trusted_workspaces?: string[] | '*' }).trusted_workspaces
                : undefined
        const workspaceId = event.team ?? 'unknown'
        if (trusted !== '*' && (!Array.isArray(trusted) || !trusted.includes(workspaceId))) {
            res.status(403).json({ error: 'workspace_not_trusted', workspace: workspaceId })
            return
        }

        // Identity resolution: same (workspace, user) tuple resolves to the
        // same AgentUser across sessions.
        const principalId = `${workspaceId}:${event.user}`
        let agentUserId = principalId
        if (deps.identities) {
            const agentUser = await deps.identities.findOrCreate({
                team_id: resolved.application.team_id,
                application_id: resolved.application.id,
                principal_kind: 'slack',
                principal_id: principalId,
                metadata: { workspace: workspaceId, slack_user: event.user },
            })
            agentUserId = agentUser.id
        }

        const externalKey = `slack:${event.channel}:${event.thread_ts ?? event.ts}`
        const slackPrincipal = {
            kind: 'slack',
            team_id: resolved.application.team_id,
            id: agentUserId,
        }
        const { sessionId, isResume } = await enqueueOrResume(
            { queue: deps.queue, teamId: deps.teamId },
            {
                application: resolved.application,
                revision: resolved.revision,
                externalKey,
                seed: { role: 'user', content: event.text ?? '', timestamp: Date.now() },
                principal: slackPrincipal,
            }
        )
        res.json({ ok: true, session_id: sessionId, resumed: isResume })
    })
    return r
}

interface SlackEvent {
    type: string
    channel: string
    user: string
    team?: string
    text?: string
    ts: string
    thread_ts?: string
    bot_id?: string
}

export function verifySlackSignature(req: Request, signingSecret: string): boolean {
    const ts = req.headers['x-slack-request-timestamp']
    const sig = req.headers['x-slack-signature']
    if (typeof ts !== 'string' || typeof sig !== 'string') {
        return false
    }
    const now = Math.floor(Date.now() / 1000)
    if (Math.abs(now - parseInt(ts, 10)) > 60 * 5) {
        return false
    }
    const raw = ((req as Request & { rawBody?: string }).rawBody ?? JSON.stringify(req.body)) as string
    const base = `v0:${ts}:${raw}`
    const mac = createHmac('sha256', signingSecret).update(base).digest('hex')
    const expected = `v0=${mac}`
    if (sig.length !== expected.length) {
        return false
    }
    return timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
}
