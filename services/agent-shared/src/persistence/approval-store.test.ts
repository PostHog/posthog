import { randomUUID } from 'node:crypto'

import { AssistantMessageRecord } from '../spec/spec'
import { ApprovalStore, hashCanonicalArgs, MemoryApprovalStore, UpsertApprovalRequestInput } from './approval-store'

function fauxAssistantMessage(): AssistantMessageRecord {
    return {
        role: 'assistant',
        content: [{ type: 'text', text: 'I will run delete with id=42' }],
        timestamp: Date.now(),
    }
}

function buildInput(overrides: Partial<UpsertApprovalRequestInput> = {}): UpsertApprovalRequestInput {
    return {
        id: randomUUID(),
        session_id: 'sess-1',
        application_id: 'app-1',
        team_id: 1,
        revision_id: 'rev-1',
        turn: 1,
        tool_call_id: 'tc_abc',
        tool_name: '@posthog/team-delete',
        proposed_args: { team_id: 42 },
        assistant_message: fauxAssistantMessage(),
        approver_scope: {
            approvers: ['team_admins'],
            allow_edit: false,
            allow_agent_approver: false,
        },
        expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
        ...overrides,
    }
}

describe('MemoryApprovalStore', () => {
    let store: ApprovalStore

    beforeEach(() => {
        store = new MemoryApprovalStore()
    })

    describe('hashCanonicalArgs', () => {
        it('produces identical hashes for object-key reorderings', () => {
            const a = hashCanonicalArgs({ a: 1, b: { z: 1, y: 2 } })
            const b = hashCanonicalArgs({ b: { y: 2, z: 1 }, a: 1 })
            expect(a.equals(b)).toBe(true)
        })

        it('differs when values change', () => {
            const a = hashCanonicalArgs({ team_id: 42 })
            const b = hashCanonicalArgs({ team_id: 43 })
            expect(a.equals(b)).toBe(false)
        })
    })

    describe('upsertQueued idempotency', () => {
        it('returns the existing queued row for the same canonical args', async () => {
            const first = await store.upsertQueued(buildInput())
            expect(first.deduped).toBe(false)

            const second = await store.upsertQueued(
                buildInput({ proposed_args: { team_id: 42 }, tool_call_id: 'tc_other' })
            )
            expect(second.deduped).toBe(true)
            expect(second.request.id).toBe(first.request.id)
        })

        it('treats reordered keys as the same args', async () => {
            await store.upsertQueued(buildInput({ proposed_args: { x: 1, y: 2 } }))
            const second = await store.upsertQueued(buildInput({ proposed_args: { y: 2, x: 1 } }))
            expect(second.deduped).toBe(true)
        })

        it('creates a new row when args differ', async () => {
            const a = await store.upsertQueued(buildInput({ proposed_args: { team_id: 42 } }))
            const b = await store.upsertQueued(buildInput({ proposed_args: { team_id: 43 } }))
            expect(b.deduped).toBe(false)
            expect(b.request.id).not.toBe(a.request.id)
        })

        it('after rejection, re-issuing the same args creates a fresh row (not deduped)', async () => {
            const first = await store.upsertQueued(buildInput())
            await store.markRejected(first.request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
                reason: 'no',
            })
            const second = await store.upsertQueued(buildInput())
            expect(second.deduped).toBe(false)
            expect(second.request.id).not.toBe(first.request.id)
        })
    })

    describe('decision transitions', () => {
        it('markApproving only fires from queued', async () => {
            const { request } = await store.upsertQueued(buildInput())
            const ok = await store.markApproving(request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
            })
            expect(ok?.state).toBe('approving')

            // Second attempt is a no-op.
            const again = await store.markApproving(request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
            })
            expect(again).toBeNull()
        })

        it('markDispatched maps outcome.error to dispatched_failed', async () => {
            const { request } = await store.upsertQueued(buildInput())
            await store.markApproving(request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
            })
            const failed = await store.markDispatched(request.id, { error: 'kaboom' })
            expect(failed?.state).toBe('dispatched_failed')
            expect(failed?.dispatch_outcome).toEqual({ error: 'kaboom' })
        })

        it('markDispatched with result lands as dispatched', async () => {
            const { request } = await store.upsertQueued(buildInput())
            await store.markApproving(request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
            })
            const done = await store.markDispatched(request.id, { result: { ok: true } })
            expect(done?.state).toBe('dispatched')
            expect(done?.dispatch_outcome).toEqual({ result: { ok: true } })
        })

        it('markRejected stamps reason', async () => {
            const { request } = await store.upsertQueued(buildInput())
            const rejected = await store.markRejected(request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
                reason: 'amount too high',
            })
            expect(rejected?.state).toBe('rejected')
            expect(rejected?.decision_reason).toBe('amount too high')
        })
    })

    describe('expireQueued', () => {
        it('flips only queued rows past expires_at', async () => {
            const past = new Date(Date.now() - 1000).toISOString()
            const future = new Date(Date.now() + 60_000).toISOString()
            const expired = await store.upsertQueued(buildInput({ expires_at: past }))
            await store.upsertQueued(buildInput({ proposed_args: { team_id: 99 }, expires_at: future }))

            const flipped = await store.expireQueued(new Date().toISOString())
            expect(flipped).toHaveLength(1)
            expect(flipped[0].id).toBe(expired.request.id)
            expect((await store.get(expired.request.id))?.state).toBe('expired')
        })
    })

    describe('listings', () => {
        it('lists by session, scoped to that session only', async () => {
            const a = await store.upsertQueued(buildInput({ session_id: 's1', proposed_args: { team_id: 1 } }))
            const b = await store.upsertQueued(buildInput({ session_id: 's1', proposed_args: { team_id: 2 } }))
            await store.upsertQueued(buildInput({ session_id: 's2', proposed_args: { team_id: 3 } }))

            // Ordering across rows created in the same tick is implementation-
            // defined (the Pg impl orders by created_at DESC; ties break
            // however Pg likes). Assert membership, not order.
            const ids = (await store.listBySession('s1')).map((r) => r.id).sort()
            expect(ids).toEqual([a.request.id, b.request.id].sort())
        })

        it('filters listings by state', async () => {
            const { request } = await store.upsertQueued(buildInput({ session_id: 's1' }))
            await store.markRejected(request.id, {
                decided_by: 'user-1',
                decided_at: new Date().toISOString(),
            })
            await store.upsertQueued(buildInput({ session_id: 's1', proposed_args: { team_id: 99 } }))

            const queued = await store.listBySession('s1', { state: 'queued' })
            expect(queued).toHaveLength(1)
            expect(queued[0].state).toBe('queued')

            const rejected = await store.listBySession('s1', { state: 'rejected' })
            expect(rejected).toHaveLength(1)
            expect(rejected[0].state).toBe('rejected')
        })
    })
})
