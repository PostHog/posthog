import { AgentSpecSchema, MemorySessionQueue } from '@posthog/agent-shared-v2'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared-v2'

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
        created_by: 'u',
        created_at: 'now',
        state: 'live' as const,
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'x' }),
    }
    return { app, rev }
}

describe('enqueueOrResume', () => {
    it('creates a fresh session without externalKey', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const { isResume } = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: null,
                seed: { role: 'user', content: 'hi', timestamp: Date.now() },
            }
        )
        expect(isResume).toBe(false)
    })

    it('resumes an existing session matching externalKey', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread1',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
            }
        )
        const second = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread1',
                seed: { role: 'user', content: 'follow-up', timestamp: Date.now() },
            }
        )
        expect(second.isResume).toBe(true)
        expect(second.sessionId).toBe(first.sessionId)
        const session = await queue.get(first.sessionId)
        // Initial seed in conversation; follow-up lands in pending_inputs so
        // the runner drains it at the start of the next turn.
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('creates a new session if existing one is completed', async () => {
        const queue = new MemorySessionQueue()
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue, teamId: 1 },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread2',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
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
            }
        )
        expect(second.isResume).toBe(false)
        expect(second.sessionId).not.toBe(first.sessionId)
    })
})
