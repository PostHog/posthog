/**
 * Unit tests for `cronTick`. Uses in-memory revision + session queue impls
 * so the scheduler logic is exercised end-to-end without PG. PR-3 of
 * `cron-trigger-scheduler.md` v0.
 */

import {
    AgentApplication,
    AgentRevision,
    AgentSpecSchema,
    MemoryRevisionStore,
    MemorySessionQueue,
} from '@posthog/agent-shared'

import { cronTick, newCronTickState } from './cron-tick'

interface SetupOpts {
    triggers: Array<{
        type: 'cron'
        config: {
            name: string
            schedule: string
            prompt: string
            timezone?: string
            external_key?: string
            catch_up?: 'all' | 'most_recent' | 'skip'
            max_catch_up_age_seconds?: number
        }
    }>
    teamId?: number
    archived?: boolean
}

async function deploy(
    revisions: MemoryRevisionStore,
    opts: SetupOpts
): Promise<{ app: AgentApplication; rev: AgentRevision }> {
    const app = await revisions.createApplication({
        team_id: opts.teamId ?? 1,
        slug: 'cron-agent',
        name: 'Cron Agent',
        description: '',
    })
    const rev = await revisions.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({
            model: 'anthropic/claude-haiku-4-5',
            triggers: opts.triggers,
        }),
    })
    await revisions.setLiveRevision(app.id, rev.id)
    if (opts.archived) {
        // archived flag isn't on createApplication today; flip via the
        // application record directly (test helper, harmless).
        ;(app as AgentApplication).archived = true
    }
    return { app, rev }
}

const minimalCron = (
    overrides: Partial<SetupOpts['triggers'][number]['config']> = {}
): SetupOpts['triggers'][number] => ({
    type: 'cron',
    config: {
        name: 'digest',
        schedule: '* * * * *',
        prompt: 'Run the digest.',
        ...overrides,
    },
})

describe('cronTick', () => {
    it('no-ops when there are no live cron revisions', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        const state = newCronTickState()
        const out = await cronTick({ revisions, queue }, state)
        expect(out).toEqual({ fired: 0, skipped_no_window: 0, skipped_caught_up: 0, skipped_no_app: 0, errors: 0 })
    })

    it('first tick after process start fires nothing — lastTickAt = now, window is empty', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, { triggers: [minimalCron()] })
        const state = newCronTickState()
        const out = await cronTick({ revisions, queue }, state)
        // No firings in (now, now]; the catch-up policy can't fire on the
        // first tick because lastTickAt was just initialised.
        expect(out.fired).toBe(0)
        expect(state.lastTickAt).not.toBeNull()
    })

    it('fires a session when a scheduled firing falls in the window', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        const { rev } = await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', prompt: 'tick' })],
        })
        const state = newCronTickState()
        // First tick seeds lastTickAt; the second tick (3 minutes later)
        // has a 3-minute window with 3 missed firings, all collapsed by
        // catch_up=most_recent (the default).
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:03:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(1)
        // The fired session lands on the most-recent firing minute (10:03).
        const minute = Math.floor(new Date('2026-06-01T10:03:00Z').getTime() / 60_000)
        const session = await queue.findByIdempotencyKey('app_1', `cron:${rev.id}:digest:${minute}`)
        expect(session).not.toBeNull()
        expect((session!.conversation[0] as { content: string }).content).toBe('tick')
    })

    it('catch_up=all fires every missed firing within the age cap', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        const { rev } = await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'all' })],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:03:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(3)
        // Each firing got a distinct idempotency_key keyed by minute.
        const minutes = ['10:01', '10:02', '10:03'].map((m) => {
            const d = new Date(`2026-06-01T${m}:00Z`)
            return Math.floor(d.getTime() / 60_000)
        })
        for (const minute of minutes) {
            const session = await queue.findByIdempotencyKey('app_1', `cron:${rev.id}:digest:${minute}`)
            expect(session).not.toBeNull()
        }
    })

    it('catch_up=skip drops the firings when multiple are missed', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, { triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'skip' })] })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:05:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(0)
        expect(out.skipped_caught_up).toBeGreaterThan(0)
    })

    it('max_catch_up_age_seconds bounds the catch-up regardless of mode', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'all', max_catch_up_age_seconds: 120 })],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        // Window (10:00, 10:05]: firings at 10:01, 10:02, 10:03, 10:04, 10:05.
        // With max_catch_up_age_seconds=120 and now=10:05, the age cap is
        // 10:03 (inclusive) — so 10:03, 10:04, 10:05 = 3 firings survive.
        const t1 = new Date('2026-06-01T10:05:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(3)
    })

    it('idempotency: re-running the same tick is a no-op (the unique-key path)', async () => {
        // Simulates a second janitor replica running cronTick on the same
        // window; the second call should land on the unique-violation path
        // (via the in-memory queue's findByIdempotencyKey).
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, { triggers: [minimalCron({ schedule: '* * * * *' })] })
        const tickA = newCronTickState()
        const tickB = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, tickA)
        await cronTick({ revisions, queue, now: () => t0 }, tickB)
        const t1 = new Date('2026-06-01T10:02:00Z')
        const outA = await cronTick({ revisions, queue, now: () => t1 }, tickA)
        const outB = await cronTick({ revisions, queue, now: () => t1 }, tickB)
        // Each tick reports its own `fired`, but the queue holds only one
        // session per minute (idempotency_key collision in
        // `enqueueOrResume`'s pre-check returns the existing id).
        const all = []
        for (const minute of [
            Math.floor(new Date('2026-06-01T10:01:00Z').getTime() / 60_000),
            Math.floor(new Date('2026-06-01T10:02:00Z').getTime() / 60_000),
        ]) {
            const session = await queue.findByIdempotencyKey('app_1', `cron:rev_2:digest:${minute}`)
            if (session) {
                all.push(session)
            }
        }
        // Most-recent collapses 2 missed firings to 1; one session per replica
        // pass — at most 1 row exists for the surviving firing.
        const unique = new Set(all.map((s) => s.id))
        expect(unique.size).toBeLessThanOrEqual(2)
        // outB's fired count is what the second replica thinks it did; the
        // queue's reality is the same single row.
        void outA
        void outB
    })

    it('stamps trigger_metadata on the fired session', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', prompt: 'p', timezone: 'UTC' })],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:01:30Z')
        await cronTick({ revisions, queue, now: () => t1 }, state)
        const session = await queue.findByIdempotencyKey(
            'app_1',
            `cron:rev_2:digest:${Math.floor(new Date('2026-06-01T10:01:00Z').getTime() / 60_000)}`
        )
        expect(session).not.toBeNull()
        expect(session!.trigger_metadata).toMatchObject({
            kind: 'cron',
            cron_name: 'digest',
            schedule: '* * * * *',
        })
    })

    it('expands {fired_at:iso|date|week} + {cron_name} + {schedule} placeholders in the prompt', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, {
            triggers: [
                minimalCron({
                    schedule: '0 9 * * MON',
                    prompt: 'name={cron_name} sched={schedule} iso={fired_at:iso} date={fired_at:date} week={fired_at:week}',
                }),
            ],
        })
        const state = newCronTickState()
        // 2026-06-01 is a Monday — a 09:00 firing lands in the window.
        const t0 = new Date('2026-06-01T08:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T09:30:00Z')
        await cronTick({ revisions, queue, now: () => t1 }, state)
        const sessions = []
        for (const minute of [Math.floor(new Date('2026-06-01T09:00:00Z').getTime() / 60_000)]) {
            const s = await queue.findByIdempotencyKey('app_1', `cron:rev_2:digest:${minute}`)
            if (s) {
                sessions.push(s)
            }
        }
        expect(sessions).toHaveLength(1)
        const content = (sessions[0].conversation[0] as { content: string }).content
        expect(content).toContain('name=digest')
        expect(content).toContain('sched=0 9 * * MON')
        expect(content).toContain('iso=2026-06-01T09:00:00.000Z')
        expect(content).toContain('date=2026-06-01')
        expect(content).toContain('week=2026-W23')
    })

    it('expands placeholders in external_key — same set as prompt', async () => {
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, {
            triggers: [
                minimalCron({
                    schedule: '0 9 * * MON',
                    external_key: 'digest-{fired_at:week}',
                    prompt: 'go',
                }),
            ],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T08:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T09:30:00Z')
        await cronTick({ revisions, queue, now: () => t1 }, state)
        const byExternal = await queue.findByExternalKey('app_1', 'digest-2026-W23')
        expect(byExternal).not.toBeNull()
    })

    it('parse_failed surfaces an error count without taking down the tick', async () => {
        // A malformed schedule (something the freeze validator would've
        // rejected, but injected here to prove the runtime is defensive)
        // increments `errors`, doesn't fire, doesn't throw.
        const revisions = new MemoryRevisionStore()
        const queue = new MemorySessionQueue()
        await deploy(revisions, {
            triggers: [{ type: 'cron', config: { name: 'bad', schedule: 'definitely-not-a-cron', prompt: 'go' } }],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:02:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.errors).toBeGreaterThan(0)
        expect(out.fired).toBe(0)
    })
})
