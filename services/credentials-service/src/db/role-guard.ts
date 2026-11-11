import type { Pool } from 'pg'

import type { DatabaseConfig } from '../lib/config'

/** Production environments are named `prod-us`, `prod-eu` and so on. */
export function isProductionEnv(env: string): boolean {
    return env.startsWith('prod')
}

function userOf(url: string): string | undefined {
    try {
        return decodeURIComponent(new URL(url).username) || undefined
    } catch {
        return undefined
    }
}

/**
 * Why the runtime role may not serve integrations, or null when it may. The audit log is only
 * append-only when the runtime role does not own it and cannot change its rows. A role that
 * can would let a compromised pod erase its own trail.
 */
export async function runtimeRoleRefusal(pool: Pool, config: DatabaseConfig): Promise<string | null> {
    const runtimeUser = userOf(config.url)
    if (config.migrateUser !== undefined && runtimeUser === config.migrateUser) {
        return 'the runtime and migrate database URLs name the same user'
    }

    const result = await pool.query<{ owns: boolean; can_modify: boolean }>(
        `SELECT
            coalesce((SELECT tableowner = current_user FROM pg_tables
                      WHERE schemaname = current_schema() AND tablename = 'audit_log'), false) AS owns,
            CASE WHEN to_regclass('audit_log') IS NULL THEN false
                 ELSE has_table_privilege('audit_log', 'DELETE')
                   OR has_table_privilege('audit_log', 'UPDATE')
                   OR has_table_privilege('audit_log', 'TRUNCATE')
            END AS can_modify`
    )
    const row = result.rows[0]
    if (row?.owns) {
        return 'the runtime role owns the audit log'
    }
    if (row?.can_modify) {
        return 'the runtime role can change or delete audit log rows'
    }
    return null
}
