import { DefaultChannelTypes, WebStatsTableQueryResponse } from '~/queries/schema/schema-general'

import { hasPaidChannelTraffic } from './marketingCrossSellUtils'

describe('paid channel evidence', () => {
    it.each([
        [DefaultChannelTypes.PaidSearch, [1, 0], true],
        [DefaultChannelTypes.PaidSocial, [10, null], true],
        [DefaultChannelTypes.CrossNetwork, [2, null], true],
        [DefaultChannelTypes.PaidUnknown, [5, null], true],
        [DefaultChannelTypes.OrganicSearch, [100, null], false],
        [DefaultChannelTypes.Direct, [100, null], false],
        [DefaultChannelTypes.PaidSearch, [0, 50], false],
        ['google', [100, null], false],
    ])('classifies %s with visitors %j as %s', (channel, visitors, expected) => {
        const response: WebStatsTableQueryResponse = {
            results: [[channel, visitors]],
            columns: ['context.columns.channel_type', 'context.columns.visitors'],
        }
        expect(hasPaidChannelTraffic(response)).toBe(expected)
    })

    it('requires visitors in the response rather than treating a different metric as evidence', () => {
        expect(
            hasPaidChannelTraffic({
                results: [[DefaultChannelTypes.PaidSearch, [4, null]]],
                columns: ['channel', 'views'],
            })
        ).toBe(false)
        expect(hasPaidChannelTraffic(null)).toBe(false)
    })
})
