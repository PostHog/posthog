import type { Pool } from 'pg'

import type { DatabaseConfig } from '../lib/config'

/**
 * Any name that contains `prod`, in any case, counts as production. A typo such as `Prod-us` or
 * `prod_us` then still runs the guard, and the guard fails closed.
 */
export function isProductionEnv(env: string): boolean {
    return /prod/i.test(env)
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

    // The service resolves `audit_log` through its own search_path, so the guard resolves it the same way.
    // A row of audit_log_default or of a daily partition can be changed directly, so every table in the
    // partition tree is checked, including column-level UPDATE grants. MEMBER, unlike USAGE, also
    // counts a NOINHERIT membership, which still allows SET ROLE to the owner. The owner of a schema
    // can drop it with every table in it, so owning the schema of any audit table counts as owning it.
    const result = await pool.query<{ owns: boolean; can_modify: boolean }>(
        `WITH tree AS (
            SELECT relid FROM pg_partition_tree(to_regclass('audit_log'))
            WHERE to_regclass('audit_log') IS NOT NULL
        )
        SELECT
            coalesce(bool_or(
                pg_has_role(current_user, c.relowner, 'MEMBER')
                OR pg_has_role(current_user, n.nspowner, 'MEMBER')
            ), false) AS owns,
            coalesce(bool_or(
                has_table_privilege(t.relid, 'DELETE')
                OR has_table_privilege(t.relid, 'UPDATE')
                OR has_table_privilege(t.relid, 'TRUNCATE')
                OR has_any_column_privilege(t.relid, 'UPDATE')
            ), false) AS can_modify
        FROM tree t
        JOIN pg_class c ON c.oid = t.relid
        JOIN pg_namespace n ON n.oid = c.relnamespace`
    )
    const row = result.rows[0]
    if (row?.owns) {
        return 'the runtime role owns, or can become the owner of, the audit log or its schema'
    }
    if (row?.can_modify) {
        return 'the runtime role can change or delete audit log rows'
    }
    return null
}
