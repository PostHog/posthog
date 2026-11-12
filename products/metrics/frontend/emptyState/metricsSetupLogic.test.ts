import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { clearAllCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsHasMetricsRetrieve } from '../generated/api'
import { canViewMetrics } from '../metricsAccess'
import { metricsSetupLogic } from './metricsSetupLogic'

jest.mock('posthog-js')
jest.mock('../metricsAccess', () => ({ canViewMetrics: jest.fn() }))
jest.mock('../generated/api', () => ({ metricsHasMetricsRetrieve: jest.fn() }))
// Real backoff waits would put the error cases over the 5s test limit; the retry policy is not what these assert.
jest.mock('lib/utils/async', () => ({
    ...jest.requireActual('lib/utils/async'),
    retryWithBackoff: (fn: () => Promise<unknown>) => fn(),
}))

describe('metricsSetupLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        clearAllCachedHasData()
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

    // In the derived series experiment, the test arm skips the setup screen for spans and logs it can chart,
    // and both arms record exposure only when the team has spans or logs.
    it.each([
        [
            'test arm with spans or logs',
            { hasMetrics: false, hasDerivedSources: true, hasDerivedMetrics: true },
            'has-data',
            true,
        ],
        [
            'control arm with spans or logs',
            { hasMetrics: false, hasDerivedSources: true, hasDerivedMetrics: false },
            'needs-setup',
            true,
        ],
        [
            'no spans or logs',
            { hasMetrics: false, hasDerivedSources: false, hasDerivedMetrics: false },
            'needs-setup',
            false,
        ],
    ])('%s', async (_name, response, expected, exposed) => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockResolvedValue(response)
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe(expected)
        expect((posthog.getFeatureFlag as jest.Mock).mock.calls).toEqual(exposed ? [['metrics-derived-series']] : [])
    })

    // Derived series go away when the experiment ends or the spans and logs age out, so only ingested
    // metrics may skip detection on the next visit.
    it.each([
        ['ingested metrics', { hasMetrics: true, hasDerivedSources: true, hasDerivedMetrics: false }, true],
        ['derived series only', { hasMetrics: false, hasDerivedSources: true, hasDerivedMetrics: true }, false],
    ])('caches has-data for %s: %s', async (_name, response, cached) => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockResolvedValue(response)
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('has-data')
        metricsSetupLogic.unmount()
        const cacheKeys = Object.keys(window.localStorage).filter((key) => key.startsWith('ph-product-setup-has-data/'))
        expect(cacheKeys.length).toBe(cached ? 1 : 0)
        // A cached visit skips the first check but still re-detects once, so exposure is recorded.
        ;(posthog.getFeatureFlag as jest.Mock).mockClear()
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(posthog.getFeatureFlag as jest.Mock).toHaveBeenCalledTimes(1)
    })

    it('treats a flag-gated 403 as unknown, so a fresh alpha enrollment never surfaces an error', async () => {
        // The enrollment person property takes seconds to ingest after the user turns the
        // preview on; until then the API denies with the feature_flag_required code. That
        // window is not a detection failure, and the poll answers properly once it closes.
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockRejectedValue({ status: 403, code: 'feature_flag_required' })
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
        // A clean `unknown` answer, not a detection failure: the loader's failure path would
        // also land on `unknown`, but only after filing an error.
        expect(metricsSetupLogic.values.detectedStatus).toBe('unknown')
    })

    it('still fails open on other errors', async () => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockRejectedValue(new Error('network down'))
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
    })
})
