import { Express, Request, Response } from 'ultimate-express'
import { z } from 'zod'

import { ListSessionsFilter, SessionQuery, SessionStatus, SessionView, logger } from '@posthog/agent-core'

const STATUS_VALUES = ['available', 'running', 'completed', 'failed', 'canceled'] as const
const StatusSchema = z.enum(STATUS_VALUES)

const ListQuerySchema = z.object({
    team_id: z.coerce.number().int().optional(),
    application_id: z.string().uuid().optional(),
    revision_id: z.string().uuid().optional(),
    status: z
        .union([StatusSchema, z.array(StatusSchema)])
        .optional()
        .transform((v) => (v === undefined ? undefined : Array.isArray(v) ? v : [v])),
    created_before: z.coerce.date().optional(),
    limit: z.coerce.number().int().positive().optional(),
})

export interface SessionsRouteDeps {
    query: SessionQuery
}

export function registerSessionsRoutes(app: Express, deps: SessionsRouteDeps): void {
    app.get('/internal/sessions/:id', async (req: Request, res: Response) => {
        const id = parseSessionId(req.params.id)
        if (!id) {
            res.status(400).json({ error: 'invalid session id' })
            return
        }
        try {
            const view = await deps.query.findSession(id)
            if (!view) {
                res.status(404).json({ error: 'session not found' })
                return
            }
            res.json(viewToJson(view))
        } catch (err) {
            logger.error('agent-janitor findSession failed', { id, error: String(err) })
            res.status(503).json({ error: 'session lookup failed' })
        }
    })

    app.get('/internal/sessions', async (req: Request, res: Response) => {
        const parsed = ListQuerySchema.safeParse(req.query)
        if (!parsed.success) {
            res.status(400).json({ error: 'invalid query', issues: parsed.error.issues })
            return
        }
        const filter: ListSessionsFilter = {
            teamId: parsed.data.team_id,
            applicationId: parsed.data.application_id,
            revisionId: parsed.data.revision_id,
            status: parsed.data.status as readonly SessionStatus[] | undefined,
            createdBefore: parsed.data.created_before,
            limit: parsed.data.limit,
        }
        try {
            const results = await deps.query.listSessions(filter)
            res.json({ results: results.map(viewToJson) })
        } catch (err) {
            logger.error('agent-janitor listSessions failed', { error: String(err) })
            res.status(503).json({ error: 'session list failed' })
        }
    })

    app.post('/internal/sessions/:id/cancel', async (req: Request, res: Response) => {
        const id = parseSessionId(req.params.id)
        if (!id) {
            res.status(400).json({ error: 'invalid session id' })
            return
        }
        try {
            const view = await deps.query.cancelSession(id)
            if (!view) {
                res.status(404).json({ error: 'session not found' })
                return
            }
            res.json(viewToJson(view))
        } catch (err) {
            logger.error('agent-janitor cancelSession failed', { id, error: String(err) })
            res.status(503).json({ error: 'session cancel failed' })
        }
    })
}

function parseSessionId(raw: string | undefined): string | null {
    if (!raw) {
        return null
    }
    return z.string().uuid().safeParse(raw).success ? raw : null
}

function viewToJson(view: SessionView): Record<string, unknown> {
    return {
        id: view.id,
        team_id: view.teamId,
        application_id: view.applicationId,
        revision_id: view.revisionId,
        queue_name: view.queueName,
        status: view.status,
        scheduled: view.scheduled.toISO(),
        created: view.created.toISO(),
        last_transition: view.lastTransition.toISO(),
        last_heartbeat: view.lastHeartbeat?.toISO() ?? null,
        transition_count: view.transitionCount,
        janitor_touch_count: view.janitorTouchCount,
        state_byte_size: view.stateByteSize,
    }
}
