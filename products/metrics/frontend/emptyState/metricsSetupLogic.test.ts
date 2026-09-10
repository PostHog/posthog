import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsHasMetricsRetrieve } from '../generated/api'
import { canViewMetrics } from '../metricsAccess'
import { metricsSetupLogic } from './metricsSetupLogic'

jest.mock('../metricsAccess', () => ({ canViewMetrics: jest.fn() }))
jest.spyOn(lemonToast, 'error').mockImplementation()
jest.mock('../generated/api', () => ({ metricsHasMetricsRetrieve: jest.fn() }))

describe('metricsSetupLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.METRICS], { [FEATURE_FLAGS.METRICS]: true })
        jest.mocked(lemonToast.error).mockClear()
    })

    // Guards the status mapping the scene gate hangs off: treating "no access"
    // as "no metrics" would show the setup screen to viewers who simply cannot
    // run the check, and flipping the has-metrics branch would gate teams with
    // real samples.
    it.each([
        [false, undefined, 'unknown'],
        [true, true, 'has-data'],
        [true, false, 'needs-setup'],
    ])('access=%s, hasMetrics=%s maps to %s', async (access, hasMetrics, expected) => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(access)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockResolvedValue({ hasMetrics })
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe(expected)
    })

    // has_metrics is gated on the same flag as the product, so a flag-off check can only 403,
    // once per poll tick, and each 403 is a toast on top of the alpha splash.
    it('never calls the endpoint while the metrics flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: false })
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockResolvedValue({ hasMetrics: false })
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(metricsHasMetricsRetrieve).not.toHaveBeenCalled()
        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
    })

    // Server-side flag evaluation lags a fresh feature-preview enrollment, so an enrolled user
    // can still get a 403. The gate reads it as unknown and shows the scene, so the toast added
    // nothing, and retrying a refusal only multiplied it.
    it('asks once and stays quiet when the check is refused', async () => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockRejectedValue(
            Object.assign(new Error('feature flag required'), { status: 403 })
        )
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(metricsHasMetricsRetrieve).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).not.toHaveBeenCalled()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
    })
})
