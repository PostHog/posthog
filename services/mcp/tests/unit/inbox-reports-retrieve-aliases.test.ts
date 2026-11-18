import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'

// The report family splits on the identifier key: `inbox-reports-retrieve` takes
// `id`, but the sibling `inbox-report-artefacts-*` tools take `report_id`, and
// the scout prose calls a report's id `report_id` throughout. Agents carry that
// key over and call retrieve with `report_id`, which used to fail validation. The
// alias normalizes `report_id` to `id` so the documented call works either way.
describe('inbox-reports-retrieve report_id alias', () => {
    const schema = GENERATED_TOOLS['inbox-reports-retrieve']!().schema
    const REPORT_UUID = '01a04d4c-9994-716b-8038-10627229a016'

    it.each([
        ['id (the documented example)', { id: REPORT_UUID }, REPORT_UUID],
        ['report_id', { report_id: REPORT_UUID }, REPORT_UUID],
        ['id over report_id on conflict', { id: REPORT_UUID, report_id: 'other' }, REPORT_UUID],
    ])('accepts %s and normalizes to `id`', (_label, input, expected) => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        const data = result.data as Record<string, unknown>
        expect(data.id).toEqual(expected)
        expect(data).not.toHaveProperty('report_id')
    })

    it('still rejects a call with no identifier', () => {
        expect(schema.safeParse({}).success).toBe(false)
    })
})
