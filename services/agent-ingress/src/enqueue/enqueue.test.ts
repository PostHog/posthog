import { AgentSpecSchema, MemorySessionQueue, SessionPrincipal } from '@posthog/agent-shared'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared'

import { enqueueOrResume } from './enqueue'

function makePair(): { app: AgentApplication; rev: AgentRevision } {
    const app = {
        id: 'app1',
        team_id: 1,
        slug: 'x',
        name: 'X',
        description: '',
        live_revision_id: 'rev1',
        archived: false,
        encrypted_env: null,
    }
    const rev = {
        id: 'rev1',
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        created_at: 'now',
        state: 'live' as const,
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'x' }),
    }
    return { app, rev }
}

const ALICE: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-alice' }
const BOB: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-bob' }

describe('enqueueOrResume', () => {
    it('creates a fresh session without externalKey', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const out = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: null,
                seed: { role: 'user', content: 'hi', timestamp: Date.now() },
            }
        )
        expect(out.kind).toBe('created')
        expect(out.isResume).toBe(false)
    })

    it('resumes an existing session matching externalKey + same principal', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread1',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        const second = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread1',
                seed: { role: 'user', content: 'follow-up', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        expect(second.kind).toBe('resumed')
        expect(second.sessionId).toBe(first.sessionId)
        const session = await queue.get(first.sessionId)
        // Initial seed in conversation; follow-up lands in pending_inputs so
        // the runner drains it at the start of the next turn.
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('resumes a `completed` (open) session via external_key', async () => {
        // Under the new state machine `completed` is the open idle state —
        // external_key reuse picks it back up. Only `closed` / `failed`
        // force a fresh session.
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread2',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        await queue.update(first.sessionId, { state: 'completed' })
        const second = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread2',
                seed: { role: 'user', content: 'second', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        expect(second.kind).toBe('resumed')
        expect(second.sessionId).toBe(first.sessionId)
    })

    it('creates a new session if existing one is `closed` (terminal)', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread3',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        await queue.update(first.sessionId, { state: 'closed' })
        const second = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread3',
                seed: { role: 'user', content: 'second', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        expect(second.kind).toBe('created')
        expect(second.sessionId).not.toBe(first.sessionId)
    })

    it('denies a resume when the incoming principal does not match', async () => {
        // The Slack-thread security gap: previously a second user could
        // resume someone else's thread because principals weren't checked on
        // the externalKey resume path. Now we record a pending elevation
        // request and surface elevation_required to the trigger instead.
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread4',
                seed: { role: 'user', content: 'alice opens thread', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
            }
        )
        const second = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread4',
                seed: { role: 'user', content: 'bob replies', timestamp: Date.now() },
                principal: BOB,
                trigger: 'slack',
            }
        )
        expect(second.kind).toBe('elevation_required')
        if (second.kind !== 'elevation_required') {
            return
        }
        expect(second.sessionId).toBe(first.sessionId)
        expect(second.elevationRequestId).toMatch(/.+/)

        const session = await queue.get(first.sessionId)
        // The rejected message is NOT appended to pending_inputs — the
        // runner must not see it.
        expect(session!.pending_inputs).toHaveLength(0)
        // It IS preserved on the elevation request for replay-on-grant.
        expect(session!.pending_elevation_requests).toHaveLength(1)
        const req = session!.pending_elevation_requests[0]
        expect(req.state).toBe('pending')
        expect(req.requester.kind === 'slack' && req.requester.slack_user_id).toBe('user-bob')
        const proposed = req.proposed_message
        expect(proposed.role).toBe('user')
        if (proposed.role === 'user') {
            expect(proposed.content).toBe('bob replies')
        }
    })

    it('expires the oldest pending elevation request once the cap is exceeded', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread5',
                seed: { role: 'user', content: 'alice opens', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
            }
        )
        // Six denials — the seventh would also fit if we ever lift the cap,
        // but here we just exercise the rollover from 5 → 5.
        for (let i = 0; i < 6; i++) {
            await enqueueOrResume(
                { queue, teamId: 1 },
                {
                    application: app,
                    revision: rev,
                    externalKey: 'slack:C01:thread5',
                    seed: { role: 'user', content: `bob #${i}`, timestamp: Date.now() + i },
                    principal: { ...BOB, slack_user_id: `bob-${i}` },
                    trigger: 'slack',
                }
            )
        }
        const session = await queue.get((await queue.findByExternalKey(app.id, 'slack:C01:thread5'))!.id)
        const pendings = session!.pending_elevation_requests.filter((r) => r.state === 'pending')
        expect(pendings).toHaveLength(5)
        const expired = session!.pending_elevation_requests.filter((r) => r.state === 'expired')
        expect(expired).toHaveLength(1)
    })
})
