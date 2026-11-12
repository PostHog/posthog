import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconGraph, IconTrends } from '@posthog/icons'

import { QuillToolbarSelect } from './QuillToolbarSelect'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Insights/QuillToolbarSelect',
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

function Plain(): JSX.Element {
    const [value, setValue] = useState<number | null>(null)
    return (
        <QuillToolbarSelect
            value={value}
            onChange={setValue}
            options={[
                { value: null, label: 'All breakdown values' },
                { value: 1, label: 'Chrome' },
                { value: 2, label: 'Safari' },
            ]}
        />
    )
}

function Grouped(): JSX.Element {
    const [value, setValue] = useState('line')
    return (
        <QuillToolbarSelect
            value={value}
            onChange={setValue}
            groupLabel="Time series"
            options={[
                {
                    value: 'line',
                    icon: <IconTrends />,
                    label: 'Line chart',
                    description: 'Retention over time plotted as a continuous line for each cohort.',
                },
                {
                    value: 'bar',
                    icon: <IconGraph />,
                    label: 'Bar chart',
                    description: 'Retention over time as vertical bars for each cohort.',
                },
            ]}
        />
    )
}

export const Default: Story = { render: () => <Plain /> }

export const GroupedWithDescriptions: Story = { render: () => <Grouped /> }
