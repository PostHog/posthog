import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'

import { ExperimentRefreshJourneyController, isExperimentRefreshCommitted } from './experimentRefreshJourney'
import type { ExperimentMetricsRecalculationApi } from './generated/api.schemas'

jest.mock('lib/customerJourneys/startCustomerJourney')

describe('experiment refresh journey', () => {
    const handle = { attemptId: 'refresh-a', firstUseful: jest.fn(), finish: jest.fn(), dispose: jest.fn() }
    const groups = { primary: ['primary-a'], secondary: ['secondary-a'] }

    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(startCustomerJourney).mockReturnValue(handle)
    })

    it('starts only on the observed results surface and waits for exact committed results', () => {
        const ready = jest.fn()
        const controller = new ExperimentRefreshJourneyController(ready)
        expect(controller.start(12, 'refresh-a', groups, 'per_metric')).toBeNull()
        expect(startCustomerJourney).not.toHaveBeenCalled()
        controller.observe(true)
        controller.start(12, 'refresh-a', groups, 'per_metric')
        const exposures = { is_cached: true, timeseries: [] }
        const primary = { variant_results: [] }
        const secondary = { variant_results: [] }
        controller.exposures('refresh-a', exposures)
        expect(ready).not.toHaveBeenCalled()
        controller.group('refresh-a', 'primary', [primary], [])
        controller.group('refresh-a', 'secondary', [secondary], [])
        const snapshot = ready.mock.lastCall![0]
        expect(handle.finish).not.toHaveBeenCalled()
        expect(isExperimentRefreshCommitted(snapshot, [primary], [{ variant_results: [] }], exposures)).toBe(false)
        expect(isExperimentRefreshCommitted(snapshot, [primary], [secondary], exposures)).toBe(true)
        controller.committed('refresh-a')
        expect(handle.finish).toHaveBeenCalledWith(
            'usable',
            expect.objectContaining({ exposures_response_cached: true })
        )
    })

    it('binds recalculation results to the returned run and rejects terminal coverage gaps', () => {
        const controller = new ExperimentRefreshJourneyController(jest.fn())
        controller.observe(true)
        const observation = controller.start(12, 'refresh-a', groups, 'recalculation')!
        observation.bindRun('run-a')
        observation.results({ id: 'old-run', status: 'completed', failed_metrics: 0, metric_errors: {}, results: [] })
        expect(handle.finish).not.toHaveBeenCalled()
        observation.results({ id: 'run-a', status: 'completed', failed_metrics: 0, metric_errors: {}, results: [] })
        expect(handle.finish).toHaveBeenCalledWith('failed', expect.objectContaining({ error_type: 'query_error' }))
    })

    it('freezes required identities and waits for the complete matching recalculation before commit', () => {
        const ready = jest.fn()
        const controller = new ExperimentRefreshJourneyController(ready)
        controller.observe(true)
        const required = { primary: ['primary-a'], secondary: ['secondary-a'] }
        const observation = controller.start(12, 'refresh-a', required, 'recalculation')!
        required.primary[0] = 'replacement'
        observation.bindRun('run-a')
        const primary = { baseline: {} }
        const secondary = { baseline: {} }
        observation.results({
            id: 'run-a',
            status: 'completed',
            failed_metrics: 0,
            metric_errors: {},
            results: [
                { metric_uuid: 'primary-a', status: 'completed', error_message: null, result: primary },
                { metric_uuid: 'secondary-a', status: 'completed', error_message: null, result: secondary },
            ],
        })
        expect(ready).not.toHaveBeenCalled()
        const exposures = { timeseries: [], is_cached: false }
        controller.exposures('refresh-a', exposures)
        expect(isExperimentRefreshCommitted(ready.mock.lastCall![0], [primary], [secondary], exposures)).toBe(true)
        expect(handle.finish).not.toHaveBeenCalled()
        controller.committed('refresh-a')
        expect(handle.finish).toHaveBeenCalledWith('usable', {
            total_count: 3,
            ready_count: 3,
            failed_count: 0,
            pending_count: 0,
            exposures_response_cached: false,
        })
    })

    it('does not turn an in-progress run or a partial failure into usable results', () => {
        const ready = jest.fn()
        const controller = new ExperimentRefreshJourneyController(ready)
        controller.observe(true)
        const observation = controller.start(12, 'refresh-a', groups, 'recalculation')!
        observation.bindRun('run-a')
        controller.exposures('refresh-a', { timeseries: [] })
        const results: ExperimentMetricsRecalculationApi['results'] = [
            { metric_uuid: 'primary-a', status: 'completed', error_message: null, result: {} },
            { metric_uuid: 'secondary-a', status: 'completed', error_message: null, result: {} },
        ]
        observation.results({ id: 'run-a', status: 'in_progress', failed_metrics: 0, metric_errors: {}, results })
        controller.committed('refresh-a')
        expect(ready).not.toHaveBeenCalled()
        expect(handle.finish).not.toHaveBeenCalled()
        observation.results({ id: 'run-a', status: 'failed', failed_metrics: 1, metric_errors: {}, results })
        expect(handle.finish).toHaveBeenCalledWith('failed', expect.objectContaining({ error_type: 'query_error' }))
    })

    it.each([
        [{ code: 'clickhouse_memory_limit_exceeded', statusCode: 400 }, 'failed', 'out_of_memory'],
        [{ statusCode: 504 }, 'timed_out', 'timeout'],
        [{ statusCode: 512 }, 'failed', 'query_rejected'],
        [{ statusCode: 500 }, 'failed', 'query_error'],
    ])('preserves structured per-metric failure %j without error text', (failure, outcome, errorType) => {
        const controller = new ExperimentRefreshJourneyController(jest.fn())
        controller.observe(true)
        controller.start(12, 'refresh-a', groups, 'per_metric')
        controller.group('refresh-a', 'primary', [], [{ ...failure, detail: 'synthetic-secret' }])
        controller.committed('refresh-a')
        expect(handle.finish).toHaveBeenCalledTimes(1)
        expect(handle.finish).toHaveBeenCalledWith(outcome, { total_count: 3, error_type: errorType })
    })

    it('accepts empty required groups, ignores replaced callbacks and closes on surface removal', () => {
        const ready = jest.fn()
        const controller = new ExperimentRefreshJourneyController(ready)
        controller.observe(true)
        const old = controller.start(12, 'refresh-a', groups, 'recalculation')!
        controller.start(12, 'refresh-b', { primary: [], secondary: [] }, 'per_metric')
        old.fail('timed_out', 'timeout')
        expect(handle.finish).toHaveBeenCalledTimes(1)
        controller.exposures('refresh-b', { timeseries: [] })
        expect(ready).toHaveBeenCalledWith(expect.objectContaining({ attemptId: 'refresh-b' }))
        controller.observe(false)
        controller.committed('refresh-b')
        expect(handle.finish).toHaveBeenLastCalledWith('observation_stopped', expect.any(Object))
    })
})
