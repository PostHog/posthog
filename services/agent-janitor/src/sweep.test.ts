import {
    AgentSession,
    EMPTY_USAGE_TOTAL,
    MemorySandboxInstanceStore,
    MemorySessionQueue,
    SandboxKind,
    SandboxTerminator,
    TerminationResult,
} from '@posthog/agent-shared'

import { sweepOnce } from './sweep'

function session(id: string, state: AgentSession['state'], updatedAt: string): AgentSession {
    return {
        id,
        application_id: 'app',
        revision_id: 'rev',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state,
        conversation: [],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: updatedAt,
        updated_at: updatedAt,
    }
}

describe('sweepOnce', () => {
    it('re-queues stuck running sessions for handoff (no fail)', async () => {
        const queue = new MemorySessionQueue()
        // 'updated_at' is far in the past — beyond running threshold.
        const stuck = session('a', 'running', new Date(Date.now() - 60 * 60_000).toISOString())
        await queue.enqueue(stuck)
        const result = await sweepOnce({ queue, stuckRunningThresholdMs: 60_000 })
        expect(result.requeued).toBe(1)
        expect(result.closed).toBe(0)
        expect((await queue.get('a'))!.state).toBe('queued')
    })

    it('does NOT reap running sessions younger than threshold', async () => {
        const queue = new MemorySessionQueue()
        const fresh = session('b', 'running', new Date().toISOString())
        await queue.enqueue(fresh)
        const result = await sweepOnce({ queue, stuckRunningThresholdMs: 60_000 })
        expect(result.requeued).toBe(0)
        expect((await queue.get('b'))!.state).toBe('running')
    })

    it('closes idle `completed` (open) sessions past their TTL', async () => {
        const queue = new MemorySessionQueue()
        // An idle `completed` session under the new state machine — the
        // user never followed up. The sweep transitions it to `closed`
        // (proper terminal) after the threshold so it doesn't linger.
        const idle = session('w', 'completed', '2026-01-01T00:00:00Z')
        await queue.enqueue(idle)
        const result = await sweepOnce({
            queue,
            stuckRunningThresholdMs: 60_000,
            idleCompletedThresholdMs: 60_000,
            listIdleCompletedCandidates: async () => [idle],
            now: () => new Date('2026-05-27T00:00:00Z'),
        })
        expect(result.closed).toBe(1)
        expect((await queue.get('w'))!.state).toBe('closed')
    })

    it('respects per-agent TTL: a resume-enabled session past the floor is NOT closed', async () => {
        // The agent's spec.resume.max_completed_age_ms (7d) extends the
        // platform floor (24h). A session idle for 36h is past the floor
        // but well within the agent TTL — it should stay open until next sweep.
        const queue = new MemorySessionQueue()
        const longLived = session('lr', 'completed', new Date(Date.now() - 36 * 60 * 60_000).toISOString())
        await queue.enqueue(longLived)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [longLived],
            getResumeConfig: async () => ({ enabled: true, max_completed_age_ms: 7 * 24 * 60 * 60_000 }),
        })
        expect(result.closed).toBe(0)
        expect((await queue.get('lr'))!.state).toBe('completed')
    })

    it('per-agent TTL: resume-enabled session past its own TTL IS closed', async () => {
        const queue = new MemorySessionQueue()
        const expired = session('lr2', 'completed', new Date(Date.now() - 14 * 24 * 60 * 60_000).toISOString())
        await queue.enqueue(expired)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [expired],
            getResumeConfig: async () => ({ enabled: true, max_completed_age_ms: 7 * 24 * 60 * 60_000 }),
        })
        expect(result.closed).toBe(1)
        expect((await queue.get('lr2'))!.state).toBe('closed')
    })

    it('resume-disabled or missing config falls back to the platform floor', async () => {
        const queue = new MemorySessionQueue()
        const idle = session('lr3', 'completed', new Date(Date.now() - 36 * 60 * 60_000).toISOString())
        await queue.enqueue(idle)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [idle],
            getResumeConfig: async () => undefined,
        })
        expect(result.closed).toBe(1)
        expect((await queue.get('lr3'))!.state).toBe('closed')
    })

    it('falls back to the floor when getResumeConfig throws', async () => {
        // Don't let a transient lookup failure pin sessions open indefinitely —
        // err on the side of closing.
        const queue = new MemorySessionQueue()
        const idle = session('lr4', 'completed', new Date(Date.now() - 36 * 60 * 60_000).toISOString())
        await queue.enqueue(idle)
        const result = await sweepOnce({
            queue,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [idle],
            getResumeConfig: async () => {
                throw new Error('revision store unreachable')
            },
        })
        expect(result.closed).toBe(1)
    })

    it('ignores fresh `completed` sessions still within the idle TTL', async () => {
        const queue = new MemorySessionQueue()
        const fresh = session('c', 'completed', new Date().toISOString())
        await queue.enqueue(fresh)
        const result = await sweepOnce({
            queue,
            stuckRunningThresholdMs: 1,
            idleCompletedThresholdMs: 24 * 60 * 60_000,
            listIdleCompletedCandidates: async () => [fresh],
        })
        expect(result.closed).toBe(0)
        expect((await queue.get('c'))!.state).toBe('completed')
    })

    it('poison-pills a stuck running session after maxRetries re-queues', async () => {
        const queue = new MemorySessionQueue()
        const stuck = session('p', 'running', new Date(Date.now() - 60 * 60_000).toISOString())
        await queue.enqueue(stuck)
        const opts = { queue, stuckRunningThresholdMs: 60_000, maxRetries: 2 }

        // Reap 1 → retry_count: 0 → 1, requeued.
        // Helper to put the session back in 'running' with a stale updated_at
        // so the next sweep sees it again.
        const setStale = async (): Promise<void> => {
            await queue.update('p', { state: 'running' })
            const s = await queue.get('p')
            // Force a stale updated_at — MemorySessionQueue uses updated_at as
            // the staleness signal (PG uses claimed_at; same shape).
            ;(s as AgentSession).updated_at = new Date(Date.now() - 60 * 60_000).toISOString()
        }

        let r = await sweepOnce(opts)
        expect(r).toEqual({
            requeued: 1,
            poisoned: 0,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
        expect((await queue.get('p'))!.retry_count).toBe(1)

        await setStale()
        r = await sweepOnce(opts)
        expect(r).toEqual({
            requeued: 1,
            poisoned: 0,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
        expect((await queue.get('p'))!.retry_count).toBe(2)

        // Third reap: retry_count would go to 3, exceeds maxRetries=2 → poisoned.
        await setStale()
        r = await sweepOnce(opts)
        expect(r).toEqual({
            requeued: 0,
            poisoned: 1,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
        expect((await queue.get('p'))!.state).toBe('failed')
        expect((await queue.get('p'))!.retry_count).toBe(3)
    })

    describe('idempotency_key retention sweep', () => {
        it('nulls keys on sessions older than the TTL; recent ones untouched', async () => {
            const queue = new MemorySessionQueue()
            const now = Date.now()
            // Old session — older than 30d default; should be cleared.
            const old = session('old', 'completed', new Date(now - 40 * 86_400_000).toISOString())
            old.idempotency_key = 'cron:rev:digest:1'
            await queue.enqueue(old)
            // Recent session — within 30d; should stay.
            const fresh = session('fresh', 'completed', new Date(now - 7 * 86_400_000).toISOString())
            fresh.idempotency_key = 'cron:rev:digest:2'
            await queue.enqueue(fresh)
            // Old session that never had a key — should be a no-op.
            const empty = session('empty', 'completed', new Date(now - 100 * 86_400_000).toISOString())
            await queue.enqueue(empty)

            const r = await sweepOnce({ queue, now: () => new Date(now) })
            expect(r.cleared_idempotency_keys).toBe(1)
            expect((await queue.get('old'))!.idempotency_key).toBeNull()
            expect((await queue.get('fresh'))!.idempotency_key).toBe('cron:rev:digest:2')
            expect((await queue.get('empty'))!.idempotency_key).toBeNull()
        })

        it('respects a custom TTL', async () => {
            const queue = new MemorySessionQueue()
            const now = Date.now()
            const s = session('s', 'completed', new Date(now - 2 * 86_400_000).toISOString())
            s.idempotency_key = 'k'
            await queue.enqueue(s)
            // TTL of 1d → 2-day-old session is past the cap.
            const r = await sweepOnce({ queue, now: () => new Date(now), idempotencyKeyTtlMs: 86_400_000 })
            expect(r.cleared_idempotency_keys).toBe(1)
            expect((await queue.get('s'))!.idempotency_key).toBeNull()
        })

        it('TTL=0 disables the sweep', async () => {
            const queue = new MemorySessionQueue()
            const s = session('s', 'completed', new Date(Date.now() - 100 * 86_400_000).toISOString())
            s.idempotency_key = 'k'
            await queue.enqueue(s)
            const r = await sweepOnce({ queue, idempotencyKeyTtlMs: 0 })
            expect(r.cleared_idempotency_keys).toBe(0)
            expect((await queue.get('s'))!.idempotency_key).toBe('k')
        })
    })

    describe('sandbox reaper', () => {
        // Recording terminator — captures calls and replies per a scripted map.
        function recordingTerminator(
            replies: Partial<Record<SandboxKind, TerminationResult>> = {}
        ): SandboxTerminator & { calls: Array<{ kind: SandboxKind; id: string }> } {
            const calls: Array<{ kind: SandboxKind; id: string }> = []
            return {
                calls,
                async terminate(kind: SandboxKind, providerSandboxId: string): Promise<TerminationResult> {
                    calls.push({ kind, id: providerSandboxId })
                    return replies[kind] ?? { ok: true }
                },
            }
        }

        async function seedReady(
            store: MemorySandboxInstanceStore,
            opts: { id: string; providerKind: SandboxKind; providerSandboxId: string; ageMs: number }
        ): Promise<void> {
            const row = await store.create({
                team_id: 1,
                application_id: 'app',
                revision_id: 'rev',
                session_id: opts.id,
                provider_kind: opts.providerKind,
            })
            await store.markReady(row.id, opts.providerSandboxId)
            // The MemorySandboxInstanceStore stamps last_used_at to NOW on
            // markReady; rewind it to simulate a stale row.
            const internal = await store.get(row.id)
            if (internal) {
                internal.last_used_at = new Date(Date.now() - opts.ageMs).toISOString()
            }
        }

        it('terminates stale Modal rows + marks them terminated', async () => {
            const queue = new MemorySessionQueue()
            const sandboxInstances = new MemorySandboxInstanceStore()
            const terminator = recordingTerminator()
            await seedReady(sandboxInstances, {
                id: 's1',
                providerKind: 'modal',
                providerSandboxId: 'ap-modal-1',
                ageMs: 20 * 60_000, // 20m old, past default 10m threshold
            })

            const r = await sweepOnce({
                queue,
                sandboxInstances,
                sandboxTerminator: terminator,
            })

            expect(r.reaped_sandboxes).toBe(1)
            expect(r.sandbox_reap_failures).toBe(0)
            expect(terminator.calls).toEqual([{ kind: 'modal', id: 'ap-modal-1' }])
            const stale = await sandboxInstances.findStale(60_000)
            expect(stale).toHaveLength(0)
        })

        it('does NOT reap fresh rows whose last_used_at is within threshold', async () => {
            const queue = new MemorySessionQueue()
            const sandboxInstances = new MemorySandboxInstanceStore()
            const terminator = recordingTerminator()
            await seedReady(sandboxInstances, {
                id: 's-fresh',
                providerKind: 'modal',
                providerSandboxId: 'ap-modal-fresh',
                ageMs: 5_000, // 5s old
            })

            const r = await sweepOnce({
                queue,
                sandboxInstances,
                sandboxTerminator: terminator,
            })

            expect(r.reaped_sandboxes).toBe(0)
            expect(r.sandbox_reap_failures).toBe(0)
            expect(terminator.calls).toEqual([])
        })

        it('leaves rows whose terminator failed so the next tick retries them', async () => {
            const queue = new MemorySessionQueue()
            const sandboxInstances = new MemorySandboxInstanceStore()
            const terminator = recordingTerminator({
                modal: { ok: false, reason: 'transient network blip' },
            })
            await seedReady(sandboxInstances, {
                id: 's-failing',
                providerKind: 'modal',
                providerSandboxId: 'ap-modal-failing',
                ageMs: 20 * 60_000,
            })

            const r = await sweepOnce({
                queue,
                sandboxInstances,
                sandboxTerminator: terminator,
            })

            expect(r.reaped_sandboxes).toBe(0)
            expect(r.sandbox_reap_failures).toBe(1)
            // The row is still in `ready`/visible to findStale so the next
            // sweep tick will retry termination.
            const stillStale = await sandboxInstances.findStale(60_000)
            expect(stillStale.map((row) => row.provider_sandbox_id)).toContain('ap-modal-failing')
        })

        it('no-op when the sweep is missing either sandboxInstances or the terminator', async () => {
            const queue = new MemorySessionQueue()
            const sandboxInstances = new MemorySandboxInstanceStore()
            await seedReady(sandboxInstances, {
                id: 's',
                providerKind: 'modal',
                providerSandboxId: 'ap-1',
                ageMs: 20 * 60_000,
            })
            // Wired only the store — no terminator → reaper skipped entirely.
            const r1 = await sweepOnce({ queue, sandboxInstances })
            expect(r1.reaped_sandboxes).toBe(0)
            expect(r1.sandbox_reap_failures).toBe(0)
            // Symmetric: terminator without store → also skipped.
            const r2 = await sweepOnce({ queue, sandboxTerminator: recordingTerminator() })
            expect(r2.reaped_sandboxes).toBe(0)
        })

        it('honours a custom sandboxStaleThresholdMs', async () => {
            const queue = new MemorySessionQueue()
            const sandboxInstances = new MemorySandboxInstanceStore()
            const terminator = recordingTerminator()
            // 30s old — under the default 10m, but over a 10s custom threshold.
            await seedReady(sandboxInstances, {
                id: 's',
                providerKind: 'modal',
                providerSandboxId: 'ap-1',
                ageMs: 30_000,
            })

            const r = await sweepOnce({
                queue,
                sandboxInstances,
                sandboxTerminator: terminator,
                sandboxStaleThresholdMs: 10_000,
            })

            expect(r.reaped_sandboxes).toBe(1)
            expect(terminator.calls).toEqual([{ kind: 'modal', id: 'ap-1' }])
        })
    })
})
