import { render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { NodeKind } from '~/queries/schema/schema-general'
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
    })
})
