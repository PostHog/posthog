import { dayjs } from 'lib/dayjs'

import { samplePlaceholderColumn } from '~/queries/nodes/DataTable/sampleRows'

import { buildSamplePersonRows } from './samplePersonRows'

const NOW = dayjs('2026-10-23T12:00:00.000Z')

describe('buildSamplePersonRows', () => {
    it('puts each value in the position of its column, whatever the column order', () => {
        const rows = buildSamplePersonRows(
            ['last_seen_at', 'properties.$initial_utm_campaign', 'id', 'person_display_name -- Person', 'created_at'],
            NOW
        )

        expect(rows).toHaveLength(6)
        expect(rows[0].result).toEqual([
            '2026-10-23T11:59:00.000Z',
            samplePlaceholderColumn,
            '00000000-0000-4000-8000-000000000001',
            expect.objectContaining({ display_name: 'alice@example.com' }),
            '2026-10-21T12:00:00.000Z',
        ])
    })

    it.each([
        ['properties.email', 'carol@example.com'],
        ['person', expect.objectContaining({ distinct_ids: ['sample-distinct-id-3'] })],
    ])('fills the %s column', (column, expected) => {
        const thirdRow = buildSamplePersonRows([column], NOW)[2]

        expect(thirdRow.result).toEqual([expected])
    })
})
