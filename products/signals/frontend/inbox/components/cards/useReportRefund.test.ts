import { renderHook } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { useReportRefund } from './useReportRefund'

describe('useReportRefund', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    it.each([
        { usageBasedPricing: true, refundsEnabled: true, canRefund: false },
        { usageBasedPricing: false, refundsEnabled: true, canRefund: true },
        { usageBasedPricing: undefined, refundsEnabled: true, canRefund: true },
        { usageBasedPricing: false, refundsEnabled: false, canRefund: false },
    ])(
        'offers refunds=$canRefund with usage-based pricing=$usageBasedPricing and refunds=$refundsEnabled',
        ({ usageBasedPricing, refundsEnabled, canRefund }) => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.SIGNALS_PR_REFUNDS]: refundsEnabled,
                ...(usageBasedPricing === undefined ? {} : { [FEATURE_FLAGS.SELF_DRIVING_UBP]: usageBasedPricing }),
            })
            const report = makeReport({ implementation_pr_url: 'https://github.com/example/app/pull/1' })

            const { result } = renderHook(() => useReportRefund({ report }))

            expect(result.current.canRefund).toBe(canRefund)
        }
    )
})
