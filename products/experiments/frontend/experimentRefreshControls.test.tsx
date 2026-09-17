import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'
import { ExperimentReloadActionContainer } from 'scenes/experiments/ExperimentView/ExperimentReloadActionContainer'
import { Exposures } from 'scenes/experiments/ExperimentView/Exposures'
import { MetricRowGroup } from 'scenes/experiments/MetricsView/new/MetricRowGroup'

import { useMocks as mockEndpoints } from '~/mocks/jest'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus, InsightType } from '~/types'

import { NEW_EXPERIMENT } from './constants'
import type { ExperimentMetricsRecalculationApi } from './generated/api.schemas'

jest.mock('lib/customerJourneys/startCustomerJourney')

const metric: ExperimentMetric = {
    kind: NodeKind.ExperimentMetric,
    uuid: 'primary-a',
    metric_type: ExperimentMetricType.MEAN,
    source: { kind: NodeKind.EventsNode, event: '$pageview' },
}
const experiment: Experiment = {
    ...NEW_EXPERIMENT,
    id: 123,
    name: 'Synthetic experiment',
    start_date: '2026-09-01T00:00:00Z',
    status: ExperimentStatus.Running,
    metrics: [metric],
    metrics_secondary: [],
    saved_metrics: [],
}
const terminal: ExperimentMetricsRecalculationApi = {
    id: 'synthetic-run',
    experiment_id: 123,
    status: 'completed',
    total_metrics: 1,
    completed_metrics: 1,
    failed_metrics: 0,
    metric_errors: {},
    metric_retries: {},
    trigger: 'manual',
    created_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    query_to: null,
    is_existing: false,
    active_run: null,
    result_source: 'recalculation',
    results: [
        {
            metric_uuid: 'primary-a',
            status: 'completed',
            error_message: null,
            result: { baseline: { key: 'control' }, variant_results: [] },
        },
    ],
}

describe('experiment refresh control intent', () => {
    let logic: ReturnType<typeof experimentLogic.build>
    let metricsLogic: ReturnType<typeof experimentMetricsLogic.build>
    let events: string[]
    let queries: string[]
    let creates: jest.Mock
    let trigger: jest.SpyInstance

    async function setup(recalculation: boolean, enrolled: boolean): Promise<void> {
        localStorage.clear()
        initKeaTests()
        events = []
        queries = []
        creates = jest.fn(() => {
            events.push('request')
            return [200, terminal]
        })
        mockEndpoints({
            get: {
                '/api/projects/:team/experiments/123': () => [200, experiment],
                '/api/projects/:team/experiments/:id/metrics_recalculation/latest': () => [200, terminal],
            },
            post: {
                '/api/projects/:team/experiments/:id/metrics_recalculation': creates,
                '/api/environments/:team/query/:kind': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { kind: string } }
                    queries.push(query.kind)
                    events.push(query.kind)
                    return [
                        200,
                        query.kind === 'ExperimentExposureQuery'
                            ? { timeseries: [], total_exposures: {} }
                            : { baseline: { key: 'control' }, variant_results: [] },
                    ]
                },
            },
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            recalculation ? [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION] : [],
            {
                [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]: recalculation,
            }
        )
        logic = experimentLogic({ experimentId: 123 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setExperiment(experiment)
        logic.actions.setAutoRefresh(false, 1800)
        metricsLogic = experimentMetricsLogic({ experiment })
        metricsLogic.mount()
        await expectLogic(metricsLogic).toFinishAllListeners()
        const original = metricsLogic.actions.triggerRecalculation
        trigger = jest.spyOn(metricsLogic.actions, 'triggerRecalculation').mockImplementation((...args) => {
            events.push('dispatch')
            original(...args)
        })
        jest.mocked(startCustomerJourney).mockImplementation((options) => {
            if (!enrolled) {
                return null
            }
            events.push('journey')
            return { attemptId: options.attempt_id!, firstUseful: jest.fn(), finish: jest.fn(), dispose: jest.fn() }
        })
        logic.actions.setExperimentResultsObserved(true)
        creates.mockClear()
        queries.length = 0
        events.length = 0
    }

    afterEach(() => {
        cleanup()
        trigger?.mockRestore()
        metricsLogic?.unmount()
        logic?.unmount()
        featureFlagLogic.unmount()
        jest.useRealTimers()
    })

    it.each(
        [false, true].flatMap((recalculation) =>
            [false, true].flatMap((enrolled) =>
                ['metric', 'full'].map((control) => ({ recalculation, enrolled, control }))
            )
        )
    )(
        '$control click preserves requests (recalculation=$recalculation, enrolled=$enrolled)',
        async ({ recalculation, enrolled, control }) => {
            await setup(recalculation, enrolled)
            render(
                <BindLogic logic={experimentLogic} props={{ experimentId: 123 }}>
                    {control === 'full' ? (
                        <ExperimentReloadActionContainer
                            experiment={experiment}
                            lastRefresh={new Date().toISOString()}
                        />
                    ) : (
                        <table>
                            <tbody>
                                <MetricRowGroup
                                    metric={metric}
                                    result={null}
                                    experiment={experiment}
                                    metricType={InsightType.TRENDS}
                                    metricIndex={0}
                                    displayOrder={0}
                                    axisRange={1}
                                    isSecondary={false}
                                    isLastMetric
                                    isAlternatingRow={false}
                                    onBreakdownChange={jest.fn()}
                                    onRemoveBreakdown={jest.fn()}
                                    onBreakdownAttributionChange={jest.fn()}
                                    onBreakdownLimitChange={jest.fn()}
                                    error={{ detail: 'Synthetic metric failure' }}
                                    showDetailsModal={false}
                                />
                            </tbody>
                        </table>
                    )}
                </BindLogic>
            )
            await act(async () => {
                fireEvent.click(
                    control === 'full'
                        ? document.querySelector('[data-attr="refresh-experiment"]')!
                        : screen.getByRole('button', { name: 'Try again' })
                )
                await expectLogic(logic).toFinishAllListeners()
                await expectLogic(metricsLogic).toFinishAllListeners()
            })
            expect(trigger).toHaveBeenCalledTimes(recalculation ? 1 : 0)
            expect(creates).toHaveBeenCalledTimes(recalculation ? 1 : 0)
            expect(queries.sort()).toEqual(
                recalculation
                    ? ['ExperimentExposureQuery']
                    : control === 'full'
                      ? ['ExperimentExposureQuery', 'ExperimentQuery']
                      : ['ExperimentQuery']
            )
            if (control === 'metric') {
                expect(startCustomerJourney).not.toHaveBeenCalled()
            } else {
                expect(startCustomerJourney).toHaveBeenCalledTimes(1)
                if (enrolled && recalculation) {
                    expect(events.filter((event) => !event.startsWith('Experiment'))).toEqual([
                        'journey',
                        'dispatch',
                        'request',
                    ])
                    expect(events[0]).toBe('journey')
                }
                if (enrolled && !recalculation) {
                    expect(events[0]).toBe('journey')
                }
            }
        }
    )

    it.each(['launch', 'payloadless', 'configuration'])(
        '%s does not imply an explicit refresh intent',
        async (cause) => {
            await setup(true, true)
            mockEndpoints({ post: { '/api/projects/:team/experiments/123/launch': () => [200, experiment] } })
            if (cause === 'launch') {
                logic.actions.launchExperiment()
            } else {
                logic.actions.loadExperimentSuccess(
                    experiment,
                    cause === 'configuration' ? { triggeredBy: 'experiment_config_change' } : undefined
                )
            }
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(metricsLogic).toFinishAllListeners()
            expect(startCustomerJourney).not.toHaveBeenCalled()
            expect(trigger).toHaveBeenCalledTimes(cause === 'configuration' ? 1 : 0)
            expect(creates).toHaveBeenCalledTimes(cause === 'configuration' ? 1 : 0)
        }
    )

    it.each([false, true])(
        'stale reload control callback retains automatic work without enrollment (recalculation=%s)',
        async (recalculation) => {
            await setup(recalculation, true)
            logic.actions.setAutoRefresh(true, 1800)
            const stale = '2020-01-01T00:00:00Z'
            metricsLogic.actions.setCurrentRecalculation({ ...terminal, query_to: stale, completed_at: stale })
            await act(async () => {
                render(
                    <BindLogic logic={experimentLogic} props={{ experimentId: 123 }}>
                        <ExperimentReloadActionContainer experiment={experiment} lastRefresh={stale} />
                    </BindLogic>
                )
                await expectLogic(logic).toFinishAllListeners()
                await expectLogic(metricsLogic).toFinishAllListeners()
            })
            expect(startCustomerJourney).not.toHaveBeenCalled()
            expect(trigger).toHaveBeenCalledTimes(recalculation ? 1 : 0)
            expect(creates).toHaveBeenCalledTimes(recalculation ? 1 : 0)
            if (recalculation) {
                expect(trigger).toHaveBeenCalledWith()
            }
            expect(queries.sort()).toEqual(
                recalculation ? ['ExperimentExposureQuery'] : ['ExperimentExposureQuery', 'ExperimentQuery']
            )
        }
    )

    it.each([false, true])('exposure Retry stays exposure-only (enrolled=%s)', async (enrolled) => {
        await setup(true, enrolled)
        let release!: () => void
        const pending = new Promise<void>((resolve) => {
            release = resolve
        })
        mockEndpoints({
            post: {
                '/api/environments/:team/query/:kind': async () => {
                    queries.push('ExperimentExposureQuery')
                    await pending
                    return [200, { timeseries: [], total_exposures: {} }]
                },
            },
        })
        jest.useFakeTimers()
        act(() => logic.actions.loadExposures(true))
        render(
            <BindLogic logic={experimentLogic} props={{ experimentId: 123 }}>
                <Exposures />
            </BindLogic>
        )
        fireEvent.click(screen.getByText('Exposures'))
        await act(async () => {
            await jest.advanceTimersByTimeAsync(21000)
        })
        queries.length = 0
        fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
        await act(async () => {
            release()
            await jest.advanceTimersByTimeAsync(0)
        })
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(metricsLogic).toFinishAllListeners()
        expect(queries).toEqual(['ExperimentExposureQuery'])
        expect(trigger).not.toHaveBeenCalled()
        expect(creates).not.toHaveBeenCalled()
        expect(startCustomerJourney).not.toHaveBeenCalled()
    })
})
