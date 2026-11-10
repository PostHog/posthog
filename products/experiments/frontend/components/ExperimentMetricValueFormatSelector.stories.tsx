import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

import { ExperimentMetricValueFormatSelector } from './ExperimentMetricValueFormatSelector'

const METRIC: ExperimentMetric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.MEAN,
    source: {
        kind: NodeKind.EventsNode,
        event: 'purchase',
        math: ExperimentMetricMathType.Sum,
        math_property: 'revenue',
    },
    value_format: { type: 'currency' },
}

const meta: Meta<typeof ExperimentMetricValueFormatSelector> = {
    title: 'Experiments/ExperimentMetricValueFormatSelector',
    component: ExperimentMetricValueFormatSelector,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    render: function Render() {
        const [metric, setMetric] = useState<ExperimentMetric>(METRIC)
        return (
            <div className="max-w-prose">
                <ExperimentMetricValueFormatSelector metric={metric} handleSetMetric={setMetric} />
            </div>
        )
    },
}
export default meta

export const Default: StoryObj<typeof ExperimentMetricValueFormatSelector> = {}
