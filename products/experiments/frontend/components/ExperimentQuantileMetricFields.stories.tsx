import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ExperimentMetricType, ExperimentQuantileMetric, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricGoal } from '~/types'

import { ExperimentQuantileMetricFields } from './ExperimentQuantileMetricFields'

const METRIC: ExperimentQuantileMetric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.QUANTILE,
    goal: ExperimentMetricGoal.Decrease,
    quantile: 0.9,
    source: { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview', math_property: 'load_time_ms' },
}

const meta: Meta<typeof ExperimentQuantileMetricFields> = {
    title: 'Experiments/ExperimentQuantileMetricFields',
    component: ExperimentQuantileMetricFields,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    render: function Render() {
        const [metric, setMetric] = useState<ExperimentQuantileMetric>(METRIC)
        return (
            <div className="max-w-prose">
                <ExperimentQuantileMetricFields metric={metric} handleSetMetric={setMetric} />
            </div>
        )
    },
}
export default meta

export const Default: StoryObj<typeof ExperimentQuantileMetricFields> = {}
