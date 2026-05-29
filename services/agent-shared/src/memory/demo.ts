// End-to-end demo of the agent-memory slice.
//
// Story: two agents on team 42 — a triager and a resolver. The triager records
// incidents in its own (creator-only) memory. We show cross-session recall,
// then the access wall, then cross-agent recall after a grant, then one-hop
// link expansion, then cross-team isolation.
//
// Run from repo root:
//   <tsx> services/agent-shared/src/memory/demo.ts
// (uses the agent_runtime_queue DB; drops+recreates the agent_memory_* tables)

import pg from 'pg'

import { applySchema, dropSchema } from './schema'

const { Pool } = pg
import { Memory, type Scope } from './memory'
import { FullTextRecaller } from './recaller'

const DB_URL = process.env.AGENT_MEMORY_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue'

function show(label: string, r: { ok: boolean; error?: string; data?: unknown }): void {
    if (!r.ok) {
        console.info(`  ✗ ${label}: ${r.error}`)
        return
    }
    console.info(`  ✓ ${label}`)
}

function showPrime(label: string, r: { ok: boolean; data?: any }): void {
    const res = r.data?.results ?? []
    console.info(`  • ${label} (ranker=${r.data?.ranker}) → ${res.length} hit(s)`)
    for (const hit of res) {
        const title = hit.entry.title ?? hit.entry.summary ?? JSON.stringify(hit.entry).slice(0, 60)
        console.info(`      [${hit.relevance}] ${hit.pattern}/${hit.id}  ${title}`)
        for (const l of hit.linked ?? []) {
            console.info(`          ↳ ${l.pattern}/${l.id} (${l.label ?? 'link'}) ${l.entry.title ?? ''}`)
        }
    }
}

async function main(): Promise<void> {
    const pool = new Pool({ connectionString: DB_URL })
    await dropSchema(pool)
    await applySchema(pool)

    const mem = new Memory(pool, new FullTextRecaller())
    const triager: Scope = { teamId: 42, applicationId: 'triager' }
    const resolver: Scope = { teamId: 42, applicationId: 'resolver' }
    const otherTeam: Scope = { teamId: 99, applicationId: 'triager' }

    console.info('\n1. Triager creates its own pattern + records incidents')
    show(
        'create pattern incidents',
        await mem.createPattern(triager, {
            name: 'incidents',
            doctrine: 'Production incidents this agent has seen, with root cause.',
            facets: [
                { name: 'title', type: 'text' },
                { name: 'detail', type: 'text' },
                { name: 'root_cause', type: 'text' },
            ],
        })
    )
    const e1 = await mem.create(triager, 'incidents', {
        title: 'Database connection pool exhausted',
        detail: 'API latency spiked; Postgres rejected new connections under load.',
        root_cause: 'pgbouncer pool size too low for the new worker count',
    })
    await mem.create(triager, 'incidents', {
        title: 'Kafka consumer lag on ingestion',
        detail: 'Event processing fell behind during a traffic surge.',
        root_cause: 'consumer not scaled with partition count',
    })
    await mem.create(triager, 'incidents', {
        title: 'Slack notifications delayed',
        detail: 'Alert messages arrived an hour late.',
        root_cause: 'rate limit on the Slack channel search endpoint',
    })
    console.info('  ✓ 3 incidents recorded')

    console.info('\n2. Cross-session recall — triager primes a fresh cue')
    showPrime(
        'prime "postgres ran out of connections during high traffic"',
        await mem.prime(triager, 'postgres ran out of connections during high traffic')
    )

    console.info('\n3. Access wall — resolver (different agent) tries to read incidents')
    showPrime(
        'resolver primes the same cue',
        await mem.prime(resolver, 'postgres ran out of connections during high traffic')
    )

    console.info('\n4. Triager grants resolver read access (the cross-agent share)')
    show(
        'grant resolver read on incidents',
        await mem.grant(triager, { pattern: 'incidents', applicationId: 'resolver', access: 'read' })
    )

    console.info("\n5. Cross-agent recall — resolver primes again, now sees the triager's memory")
    showPrime(
        'resolver primes the same cue',
        await mem.prime(resolver, 'postgres ran out of connections during high traffic')
    )

    console.info('\n6. One-hop links — attach a fix to the DB incident, prime surfaces it')
    await mem.createPattern(triager, {
        name: 'fixes',
        doctrine: 'Applied fixes.',
        facets: [
            { name: 'title', type: 'text' },
            { name: 'change', type: 'text' },
        ],
    })
    const f1 = await mem.create(triager, 'fixes', {
        title: 'Raised pgbouncer pool size',
        change: 'default_pool_size 20 → 80',
    })
    await mem.link(
        triager,
        { pattern: 'incidents', id: (e1.data as any).id },
        { pattern: 'fixes', id: (f1.data as any).id },
        'resolved-by'
    )
    showPrime('prime "connection pool problem"', await mem.prime(triager, 'connection pool problem'))

    console.info('\n7. Cross-team isolation — team 99 agent primes, sees nothing of team 42')
    showPrime(
        'team-99 triager primes the DB cue',
        await mem.prime(otherTeam, 'postgres ran out of connections during high traffic')
    )

    await pool.end()
    console.info('\nDEMO COMPLETE.')
}

main().catch((err) => {
    console.error('DEMO FAILED:', err)
    process.exit(1)
})
