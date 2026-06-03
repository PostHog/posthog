/**
 * Wrapper around `new Pool` that flips on SSL for non-local Postgres hosts.
 *
 * Aurora's `pg_hba.conf` requires SSL for the agent-* DB users (`hostssl`
 * only). The chart helper builds DSNs without `?sslmode=require`, so we
 * have to opt in client-side — otherwise the runner / ingress / janitor
 * boot loops with `no pg_hba.conf entry for host ..., no encryption`.
 *
 * Dev (localhost) Postgres usually doesn't speak SSL, so we leave it off
 * when the hostname is loopback. `rejectUnauthorized: false` matches what
 * the in-cluster pgbouncer does when terminating SSL to Aurora — Aurora
 * uses the AWS RDS CA which Node doesn't trust out of the box, and we
 * don't want every service to bundle the CA.
 */

// `pg` is CommonJS (`module.exports = new PG(...)`), so Node's ESM loader
// can't statically detect named exports. Destructure off the default import
// at runtime instead of `import { Pool } from 'pg'` — the named-import form
// works under vitest (its loader patches CJS interop) but fails at boot
// under `tsx watch` with "does not provide an export named 'Pool'".
import pg from 'pg'
import type { Pool as PoolType, PoolConfig } from 'pg'
const { Pool } = pg

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', ''])

function isLocalHost(connectionString: string): boolean {
    try {
        return LOCAL_HOSTS.has(new URL(connectionString).hostname)
    } catch {
        return false
    }
}

export function createAgentPool(
    connectionString: string,
    options: Omit<PoolConfig, 'connectionString' | 'ssl'> = {}
): PoolType {
    return new Pool({
        connectionString,
        ssl: isLocalHost(connectionString) ? false : { rejectUnauthorized: false },
        ...options,
    })
}
