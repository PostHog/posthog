import { render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { CachedLegacyExperimentQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { legacyExperimentLogic } from 'products/experiments/frontend/legacy/legacyExperimentLogic'

import { LegacyDataCollection } from './LegacyDataCollection'

describe('LegacyDataCollection', () => {
    it('reports no participants for a response in the new ExperimentQuery format', () => {
        initKeaTests()

        const experiment = {
            id: 1,
            start_date: '2026-09-01T00:00:00Z',
            metrics: [{ kind: NodeKind.ExperimentMetric, metric_type: 'funnel', uuid: 'm1', series: [] }],
            metrics_secondary: [],
            saved_metrics: [],
        } as unknown as Experiment

        const props = { experimentId: 1, experiment }
        const logic = legacyExperimentLogic(props)
        logic.mount()

        // A legacy experiment holding a new-format metric gets this shape back: the same `kind`,
        // but no `insight`, which the funnel participant total reads.
        logic.actions.setLegacyPrimaryMetricsResults([
            {
                kind: NodeKind.ExperimentQuery,
                metric: null,
                baseline: { key: 'control', number_of_samples: 100, sum: 10, sum_squares: 10 },
                variant_results: [{ key: 'test', number_of_samples: 100, sum: 20, sum_squares: 20 }],
            },
        ] as unknown as CachedLegacyExperimentQueryResponse[])

        render(
            <BindLogic logic={legacyExperimentLogic} props={props}>
                <LegacyDataCollection />
            </BindLogic>
        )

        expect(screen.getAllByText('0.00% complete')).toHaveLength(1)
    })
})
