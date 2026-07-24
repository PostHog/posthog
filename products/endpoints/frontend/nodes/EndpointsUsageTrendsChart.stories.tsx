import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { EndpointsUsageTrendsChart } from './EndpointsUsageTrendsNode'

const meta: Meta<typeof EndpointsUsageTrendsChart> = {
    title: 'Endpoints/UsageTrendsChart',
    component: EndpointsUsageTrendsChart,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof EndpointsUsageTrendsChart>

const DAYS = ['2026-07-01', '2026-07-02', '2026-07-03', '2026-07-04', '2026-07-05', '2026-07-06', '2026-07-07']

function Stage({ children }: { children: ReactNode }): JSX.Element {
    return <div className="w-[760px]">{children}</div>
}

// Single line series — request counts over a week.
export const Requests: Story = {
    render: () => (
        <Stage>
            <EndpointsUsageTrendsChart
                metric="requests"
                results={DAYS.map((date, i) => ({ date, value: [420, 380, 510, 470, 560, 610, 540][i] }))}
            />
        </Stage>
    ),
}

// Area fill + byte scaling (values land in the MB range).
export const BytesReadArea: Story = {
    render: () => (
        <Stage>
            <EndpointsUsageTrendsChart
                metric="bytes_read"
                results={DAYS.map((date, i) => ({
                    date,
                    value: [12, 18, 15, 22, 19, 27, 24][i] * 1024 * 1024,
                }))}
            />
        </Stage>
    ),
}

// Multiple endpoints broken down into a stacked legend.
export const Breakdown: Story = {
    render: () => {
        const byEndpoint: Record<string, number[]> = {
            '/api/events': [210, 190, 260, 240, 300, 330, 290],
            '/api/persons': [90, 110, 80, 130, 120, 140, 100],
            '/api/insights': [40, 55, 60, 45, 70, 65, 80],
        }
        return (
            <Stage>
                <EndpointsUsageTrendsChart
                    metric="requests"
                    results={DAYS.flatMap((date, i) =>
                        Object.entries(byEndpoint).map(([breakdown, values]) => ({ date, breakdown, value: values[i] }))
                    )}
                />
            </Stage>
        )
    },
}
