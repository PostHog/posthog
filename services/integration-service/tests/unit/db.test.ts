import type { Pool } from 'pg'
import { describe, expect, it, vi } from 'vitest'

import { applySchema } from '@/db/client'

describe('applySchema', () => {
    it('retries once when concurrent boots race the catalog', async () => {
        const query = vi
            .fn()
            .mockRejectedValueOnce(
                new Error('duplicate key value violates unique constraint "pg_type_typname_nsp_index"')
            )
            .mockResolvedValue({ rows: [] })

        await expect(applySchema({ query } as unknown as Pool)).resolves.toBeUndefined()
        expect(query).toHaveBeenCalledTimes(2)
    })

    it('surfaces the error when the retry also fails', async () => {
        const query = vi.fn().mockRejectedValue(new Error('permission denied'))

        await expect(applySchema({ query } as unknown as Pool)).rejects.toThrow('permission denied')
        expect(query).toHaveBeenCalledTimes(2)
    })
})
