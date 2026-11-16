import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

import { ExperimentMetricValueFormatSection } from './ExperimentMetricValueFormatSection'

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

const meta: Meta<typeof ExperimentMetricValueFormatSection> = {
    title: 'Experiments/ExperimentMetricValueFormatSection',
    component: ExperimentMetricValueFormatSection,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    render: function Render() {
        const [metric, setMetric] = useState<ExperimentMetric>(METRIC)
        return (
            <div className="max-w-prose">
                <ExperimentMetricValueFormatSection metric={metric} handleSetMetric={setMetric} />
            </div>
        )
    },
}
export default meta

export const Default: StoryObj<typeof ExperimentMetricValueFormatSection> = {}
