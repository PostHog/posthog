/**
 * Wrapper around `new Pool` that flips on SSL only for a *direct external*
 * Postgres host.
 *
 * Aurora's `pg_hba.conf` requires SSL for the agent-* DB users (`hostssl`
 * only). The chart helper builds DSNs without `?sslmode=require`, so we
 * have to opt in client-side — otherwise the runner / ingress / janitor
 * boot loops with `no pg_hba.conf entry for host ..., no encryption`.
 *
 * But when the DB is routed through the in-cluster pgbouncer, node connects
 * to the bouncer (a bare k8s service name) which speaks *plaintext* to clients
 * and carries SSL only on its own hop to Aurora. Requesting SSL there fails
 * with "The server does not support SSL connections". So SSL is on only for an
 * external (dotted, non-`.svc`) host; off for loopback + in-cluster.
 * `rejectUnauthorized: false` is used for the external case because Aurora's
 * RDS CA isn't in Node's trust store and we don't bundle it.
 */

// `pg` is CommonJS (`module.exports = new PG(...)`), so Node's ESM loader
// can't statically detect named exports. Destructure off the default import
// at runtime instead of `import { Pool } from 'pg'` — the named-import form
// works under vitest (its loader patches CJS interop) but fails at boot
// under `tsx watch` with "does not provide an export named 'Pool'".
import pg from 'pg'
import type { Pool as PoolType, PoolConfig } from 'pg'
const { Pool } = pg

// team_id / created_by_id are BIGINT (Django's ProductTeamModel uses
// BigIntegerField), but the agent code threads them as JS numbers. node-postgres
// returns int8 as a string by default to avoid precision loss — parse it back to
// a number. These ids comfortably fit in Number.MAX_SAFE_INTEGER.
pg.types.setTypeParser(20, (value: string | null) => (value === null ? null : Number.parseInt(value, 10)))

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', ''])

/**
 * Client SSL is needed only for a *direct* external Postgres (Aurora RDS, whose
 * `pg_hba` is `hostssl`-only). It must NOT be requested for an in-cluster host —
 * loopback, a bare k8s service name (single label, e.g. `pgbouncer-agent-platform-write`),
 * or a `.svc.cluster.local` FQDN — because the in-cluster pgbouncer terminates
 * plaintext on the client side (the bouncer→Aurora hop carries SSL, not node→bouncer).
 * Requesting SSL there fails with "The server does not support SSL connections".
 */
export function needsClientSsl(connectionString: string): boolean {
    let host: string
    try {
        host = new URL(connectionString).hostname
    } catch {
        return false
    }
    if (LOCAL_HOSTS.has(host)) {
        return false
    }
    if (!host.includes('.') || host.endsWith('.svc.cluster.local') || host.endsWith('.svc')) {
        return false
    }
    return true
}

export function createAgentPool(
    connectionString: string,
    options: Omit<PoolConfig, 'connectionString' | 'ssl'> = {}
): PoolType {
    return new Pool({
        connectionString,
        // Deliberate — see the file header: Aurora's RDS CA isn't in Node's trust
        // store and we don't bundle it. Off for in-cluster hosts (pgbouncer speaks
        // plaintext to clients); on only for a direct external cluster.
        // nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
        ssl: needsClientSsl(connectionString) ? { rejectUnauthorized: false } : false,
        ...options,
    })
}
