import { summarizeProtocolVersions } from './protocolVersions'

describe('summarizeProtocolVersions', () => {
    it.each([
        { name: 'empty', rows: [], expected: { totalCalls: 0, unknownCalls: 0, legacyCalls: 0 } },
        {
            name: 'mixed eras',
            rows: [
                { protocol_version: 'draft', is_current: true, total_calls: 5 },
                { protocol_version: '2026-07-28', is_current: true, total_calls: 50 },
                { protocol_version: '2025-06-18', is_current: false, total_calls: 100 },
                { protocol_version: 'v2', is_current: false, total_calls: 15 },
                { protocol_version: 'Other', is_current: false, total_calls: 20 },
                { protocol_version: 'Unknown', is_current: false, total_calls: 40 },
            ],
            expected: { totalCalls: 230, unknownCalls: 40, legacyCalls: 135 },
        },
    ])('sums calls for $name', ({ rows, expected }) => {
        expect(summarizeProtocolVersions(rows)).toEqual(expected)
    })
})
