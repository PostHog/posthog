import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { MetricsGroupByButton } from './MetricsGroupByButton'

const meta: Meta<typeof MetricsGroupByButton> = {
    title: 'Metrics/Group by',
    component: MetricsGroupByButton,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/metrics/values/': { results: [] },
                '/api/projects/:team_id/metrics/attributes/': {
                    results: [
                        { name: 'service_name', series_count: 12000 },
                        { name: 'environment', series_count: 8000 },
                        { name: 'k8s.pod.name', series_count: 350 },
                        { name: 'resource.attribute.with.a.long.name', series_count: 25 },
                    ],
                    count: 4,
                },
            },
        }),
    ],
    parameters: { layout: 'padded' },
    render: function Render() {
        const [groupByKeys, setGroupByKeys] = useState<string[]>([])
        return <MetricsGroupByButton groupByKeys={groupByKeys} onChange={setGroupByKeys} disabledReason={null} />
    },
}

export default meta
type Story = StoryObj<typeof MetricsGroupByButton>
export const Default: Story = {
    play: async () => {
        // The trigger is not in the DOM yet when the play function starts, and a bare
        // `querySelector(...)?.click()` silently does nothing when it misses — the dropdown
        // then never opens and the attribute fetch never fires.
        const trigger = await waitFor(() => {
            const element = document.querySelector<HTMLElement>('[data-attr="metrics-viewer-group-by-button"]')
            if (!element) {
                throw new Error('Group by button is not rendered')
            }
            return element
        })
        trigger.click()
        await waitFor(() => {
            if (!document.querySelector('.tabular-nums')) {
                throw new Error('Series counts are not visible')
            }
        })
    },
}
