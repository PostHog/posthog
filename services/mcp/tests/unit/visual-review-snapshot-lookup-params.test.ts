import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/visual_review'

// Both run-scoped snapshot lookups need a run id AND a snapshot identifier. Production
// traces show agents holding one snapshot row and sending only part of that pair: its
// `run_id` key instead of `id`, or `id` alone with no `identifier`. The alias covers the
// first; the second must keep failing rather than quietly widening to the whole run.
describe('visual review snapshot lookup params', () => {
    const RUN_ID = '3f1c9f0e-2b7a-4a5f-9c1d-8e6b2a4f7d31'

    describe.each([['visual-review-runs-snapshot-history-list'], ['visual-review-runs-tolerated-hashes-list']])(
        '%s',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema

            it.each([
                ['id', { id: RUN_ID, identifier: 'Button--default' }],
                ['run_id', { run_id: RUN_ID, identifier: 'Button--default' }],
            ])('accepts the run id as %s', (_label, input) => {
                const result = schema.safeParse(input)
                expect(result.success).toBe(true)
                const data = result.data as Record<string, unknown>
                expect(data.id).toBe(RUN_ID)
                expect(data).not.toHaveProperty('run_id')
            })

            it.each([
                ['identifier is omitted', { id: RUN_ID }],
                ['the run id is omitted', { identifier: 'Button--default' }],
            ])('rejects the call when %s', (_label, input) => {
                expect(schema.safeParse(input).success).toBe(false)
            })
        }
    )
})
