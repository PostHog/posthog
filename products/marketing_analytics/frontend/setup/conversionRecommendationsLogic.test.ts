import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { ConversionRecommendationStateApi } from '../generated/api.schemas'
import { conversionRecommendationsLogic } from './conversionRecommendationsLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    marketingAnalyticsConversionRecommendationsRetrieve: jest.fn(),
    marketingAnalyticsConversionRecommendationsStartCreate: jest.fn(),
}))

const empty: ConversionRecommendationStateApi = {
    latest_run: null,
    result_run: null,
    results: { recommendations: [], limitations: [] },
    can_generate: true,
    generation_disabled_reason: null,
}
const run = {
    id: 'analysis',
    status: 'completed' as const,
    lookback_days: 30,
    date_from: '2026-01-01',
    date_to: '2026-01-31',
    created_at: '2026-01-31',
    completed_at: '2026-01-31',
    error: '',
}
const complete: ConversionRecommendationStateApi = { ...empty, latest_run: run, result_run: run }

describe('conversion recommendation lifecycle', () => {
    beforeEach(() => {
        useMocks({})
        initKeaTests()
        jest.clearAllMocks()
    })

    it('starts once automatically and only updates after an explicit action', async () => {
        jest.mocked(api.marketingAnalyticsConversionRecommendationsRetrieve)
            .mockResolvedValueOnce(empty)
            .mockResolvedValue(complete)
        jest.mocked(api.marketingAnalyticsConversionRecommendationsStartCreate).mockResolvedValue(complete)
        const logic = conversionRecommendationsLogic({ projectId: 17, enabled: true, userId: 'reader' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenCalledTimes(1)
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenLastCalledWith('17', {
            refresh: false,
        })
        await expectLogic(logic, () => logic.actions.loadRecommendations()).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenCalledTimes(1)
        await expectLogic(logic, () => logic.actions.requestAnalysis(true)).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenLastCalledWith('17', {
            refresh: true,
        })
        logic.unmount()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenCalledTimes(2)
        logic.unmount()
    })

    it('preserves previous results and blocks duplicate update clicks while the request is in flight', async () => {
        jest.mocked(api.marketingAnalyticsConversionRecommendationsRetrieve).mockResolvedValue(complete)
        let resolve!: (state: ConversionRecommendationStateApi) => void
        jest.mocked(api.marketingAnalyticsConversionRecommendationsStartCreate).mockReturnValue(
            new Promise((done) => {
                resolve = done
            })
        )
        const logic = conversionRecommendationsLogic({ projectId: 17, enabled: true, userId: 'reader' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.requestAnalysis(true)
        logic.actions.requestAnalysis(true)
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenCalledTimes(1)
        expect(logic.values.state?.result_run).toEqual(run)
        resolve({
            ...complete,
            latest_run: { ...run, id: 'update', status: 'failed', lookback_days: 14, error: 'Retry the analysis.' },
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.state?.result_run).toEqual(run)
        expect(logic.values.state?.latest_run?.status).toBe('failed')
        expect(api.marketingAnalyticsConversionRecommendationsStartCreate).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it.each(['loadRecommendationsSuccess', 'startAnalysisSuccess'] as const)(
        'starts the cooldown at 60 minutes when %s receives a newly completed scan',
        async (successAction) => {
            const now = jest.spyOn(Date, 'now').mockReturnValue(0)
            const logic = conversionRecommendationsLogic({ projectId: 17, enabled: false, userId: 'reader' })
            logic.mount()
            try {
                now.mockReturnValue(5000)
                const completedRun = { ...run, completed_at: new Date(5000).toISOString() }
                logic.actions[successAction]({ ...complete, latest_run: completedRun, result_run: completedRun })
                await expectLogic(logic).toFinishAllListeners()
                expect(logic.values.scanDisabledReason).toBe('You can scan again in 60 minutes.')
            } finally {
                logic.unmount()
                now.mockRestore()
            }
        }
    )

    it('does not query when disabled and keeps another project or reader in a separate state', async () => {
        const disabled = conversionRecommendationsLogic({ projectId: 17, enabled: false, userId: 'reader' })
        disabled.mount()
        await expectLogic(disabled).toFinishAllListeners()
        expect(api.marketingAnalyticsConversionRecommendationsRetrieve).not.toHaveBeenCalled()
        const other = conversionRecommendationsLogic({ projectId: 18, enabled: false, userId: 'reader' })
        const otherReader = conversionRecommendationsLogic({ projectId: 17, enabled: false, userId: 'another-reader' })
        expect(other.key).not.toBe(disabled.key)
        expect(otherReader.key).not.toBe(disabled.key)
        disabled.unmount()
    })
})
