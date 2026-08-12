import { Pool } from 'pg'

export function createPostgresPool(databaseUrl: string): Pool {
    return new Pool({ connectionString: databaseUrl })
}

export async function isPostgresReady(pool: Pool): Promise<boolean> {
    try {
        await pool.query('SELECT 1')
        return true
    } catch {
        return false
    }
}
