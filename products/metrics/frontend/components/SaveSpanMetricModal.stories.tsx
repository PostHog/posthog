import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { saveSpanMetricLogic } from './saveSpanMetricLogic'
import { SaveSpanMetricModal } from './SaveSpanMetricModal'
import { DERIVED_SPAN_DURATION, DERIVED_SPAN_REQUESTS, buildSpanMetricRuleDraft } from './spanMetricRuleDraft'

type StoryArgs = { draft: NonNullable<ReturnType<typeof buildSpanMetricRuleDraft>> }

function OpenModal({ draft }: StoryArgs): JSX.Element {
    const { openSaveSpanMetric } = useActions(saveSpanMetricLogic)
    useEffect(() => {
        openSaveSpanMetric(draft)
    }, [draft, openSaveSpanMetric])
    return <SaveSpanMetricModal />
}

const meta: Meta<StoryArgs> = {
    title: 'Metrics/Save as metric',
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/logs/metric_rules/': { results: [] } } })],
    parameters: {
        testOptions: { snapshotTargetSelector: '.LemonModal', waitForSelector: '#save-span-metric-name' },
    },
    render: (args) => <OpenModal {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const Requests: Story = {
    args: {
        draft: buildSpanMetricRuleDraft(
            DERIVED_SPAN_REQUESTS,
            [{ key: 'service.name', op: 'eq', value: 'checkout' }],
            ['span.name']
        )!,
    },
}

export const DurationWithDroppedFilter: Story = {
    args: {
        draft: buildSpanMetricRuleDraft(
            DERIVED_SPAN_DURATION,
            [
                { key: 'deployment.environment', op: 'eq', value: 'production' },
                { key: 'span.status_code', op: 'regex', value: 'error|unset' },
            ],
            ['service.name']
        )!,
    },
}
