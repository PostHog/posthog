import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { CachedLegacyExperimentQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment, InsightType } from '~/types'

import { legacyExperimentLogic } from 'products/experiments/frontend/legacy/legacyExperimentLogic'

import { LegacyDeltaChart } from './LegacyDeltaChart'

describe('LegacyDeltaChart', () => {
    it('degrades to an empty chart for a response in the new ExperimentQuery format', () => {
        initKeaTests()

        const experiment = {
            id: 1,
            start_date: '2026-09-01T00:00:00Z',
            metrics: [{ kind: NodeKind.ExperimentMetric, metric_type: 'funnel', uuid: 'm1', series: [] }],
            metrics_secondary: [],
            saved_metrics: [],
        } as unknown as Experiment

        const props = { experimentId: 1, experiment }
        legacyExperimentLogic(props).mount()

        // A legacy experiment holding a new-format metric gets this shape back: the same `kind`,
        // but no `metric` and none of the per-variant fields the chart reads.
        const result = {
            kind: NodeKind.ExperimentQuery,
            metric: null,
            baseline: { key: 'control', number_of_samples: 100, sum: 10, sum_squares: 10 },
            variant_results: [{ key: 'test', number_of_samples: 100, sum: 20, sum_squares: 20 }],
        }

        render(
            <BindLogic logic={legacyExperimentLogic} props={props}>
                <LegacyDeltaChart
                    isSecondary={false}
                    result={result}
                    error={null}
                    variants={[{ key: 'control' }, { key: 'test' }]}
                    metricType={InsightType.FUNNELS}
                    displayOrder={0}
                    isFirstMetric={true}
                    metric={experiment.metrics[0]}
                    tickValues={[-1, 0, 1]}
                    chartBound={1}
                />
            </BindLogic>
        )

        expect(screen.getAllByText('Not enough data yet')).toHaveLength(2)
        // The top-level `significant` field is absent on this response, so the view must not
        // claim a conclusion it has not computed.
        expect(screen.queryByText('Not significant')).toBeNull()
    })

    it('keeps the significance badge for a legacy response', () => {
        initKeaTests()

        const experiment = {
            id: 1,
            start_date: '2026-09-01T00:00:00Z',
            metrics: [{ kind: NodeKind.ExperimentFunnelsQuery, uuid: 'm1' }],
            metrics_secondary: [],
            saved_metrics: [],
        } as unknown as Experiment

        const props = { experimentId: 1, experiment }
        const logic = legacyExperimentLogic(props)
        logic.mount()

        const result = {
            kind: NodeKind.ExperimentQuery,
            metric: { kind: NodeKind.ExperimentMetric, metric_type: 'funnel' },
            significant: true,
            variants: [
                { key: 'control', success_count: 10, failure_count: 90 },
                { key: 'test', success_count: 30, failure_count: 70 },
            ],
        }

        logic.actions.setLegacyPrimaryMetricsResults([result] as unknown as CachedLegacyExperimentQueryResponse[])

        render(
            <BindLogic logic={legacyExperimentLogic} props={props}>
                <LegacyDeltaChart
                    isSecondary={false}
                    result={result}
                    error={null}
                    variants={[{ key: 'control' }, { key: 'test' }]}
                    metricType={InsightType.FUNNELS}
                    displayOrder={0}
                    isFirstMetric={true}
                    metric={experiment.metrics[0]}
                    tickValues={[-1, 0, 1]}
                    chartBound={1}
                />
            </BindLogic>
        )

        expect(screen.getByText('Significant')).toBeTruthy()
    })

    it('disables Details for a response in the new ExperimentQuery format', async () => {
        initKeaTests()

        const experiment = {
            id: 1,
            start_date: '2026-09-01T00:00:00Z',
            metrics: [],
            metrics_secondary: [{ kind: NodeKind.ExperimentMetric, metric_type: 'funnel', uuid: 'm1', series: [] }],
            saved_metrics: [],
        } as unknown as Experiment

        const props = { experimentId: 1, experiment }
        const logic = legacyExperimentLogic(props)
        logic.mount()

        // Same shape as above. Opening the details modal reads `variants` through the summary
        // table, so the button must not be clickable for it.
        const result = {
            kind: NodeKind.ExperimentQuery,
            metric: null,
            baseline: { key: 'control', number_of_samples: 100, sum: 10, sum_squares: 10 },
            variant_results: [{ key: 'test', number_of_samples: 100, sum: 20, sum_squares: 20 }],
        }

        logic.actions.setLegacySecondaryMetricsResults([result] as unknown as CachedLegacyExperimentQueryResponse[])

        render(
            <BindLogic logic={legacyExperimentLogic} props={props}>
                <LegacyDeltaChart
                    isSecondary={true}
                    result={result}
                    error={null}
                    variants={[{ key: 'control' }, { key: 'test' }]}
                    metricType={InsightType.FUNNELS}
                    displayOrder={0}
                    isFirstMetric={true}
                    metric={experiment.metrics_secondary[0]}
                    tickValues={[-1, 0, 1]}
                    chartBound={1}
                />
            </BindLogic>
        )

        const detailsButton = screen.getByText('Details').closest('button') as HTMLButtonElement
        expect(detailsButton.getAttribute('aria-disabled')).toBe('true')

        await userEvent.click(detailsButton)
        expect(screen.queryByText('Metric results')).toBeNull()
    })
})
