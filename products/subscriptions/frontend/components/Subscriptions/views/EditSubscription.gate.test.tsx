import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'

import { isFreeTierCreateAtLimit } from './EditSubscription'

const LIMIT = SubscriptionFreeTierLimit.COUNT

describe('EditSubscription free-tier gate', () => {
    it.each([
        ['empty (first use)', 0, false],
        ['one below the limit boundary', LIMIT - 1, false],
        ['at the limit', LIMIT, true],
        ['over the limit', LIMIT + 1, true],
    ])('blocks the next create when %s (count=%i) -> %s', (_desc, count, expected) => {
        expect(isFreeTierCreateAtLimit(count)).toBe(expected)
    })

    it('fails open while the count is unknown (null) so the form shows; backend enforces the hard limit', () => {
        expect(isFreeTierCreateAtLimit(null)).toBe(false)
    })
})
