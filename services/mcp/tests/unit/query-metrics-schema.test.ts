import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/metrics'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

function querySchema(): z.ZodTypeAny {
    const factory = GENERATED_TOOLS['query-metrics'] as () => ToolBase<ZodObjectAny>
    return factory().schema as z.ZodTypeAny
}

describe('query-metrics schema', () => {
    it('sends a PromQL query on without builder fields', () => {
        const result = querySchema().safeParse({ query: { promql: 'sum(rate(http_requests_total[5m]))' } })

        expect(result.success).toBe(true)
        expect(result.data).toHaveProperty('query', { promql: 'sum(rate(http_requests_total[5m]))' })
    })
})
