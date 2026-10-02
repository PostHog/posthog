import type { Meta, StoryObj } from '@storybook/react'

import { reportCheckProgressFixture } from '../../__mocks__/reportCheckProgressMocks'
import { reportMetricsFixture } from '../../__mocks__/reportMetricMocks'
import { ReportCheckProgress } from './ReportCheckProgress'

const meta: Meta<typeof ReportCheckProgress> = {
    title: 'Scenes-App/Inbox/Detail/Monitoring progress',
    component: ReportCheckProgress,
    parameters: { layout: 'centered' },
    args: { progress: reportCheckProgressFixture, loading: false, metric: reportMetricsFixture[0] },
    decorators: [
        (Story) => (
            <div className="w-[32rem] max-w-full p-4">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof ReportCheckProgress>

export const OnTrack: Story = {}
export const OffTrack: Story = {
    args: {
        progress: {
            ...reportCheckProgressFixture,
            status: 'off_track',
            value: 20,
            sample_size: 20,
            points:
                reportCheckProgressFixture.points?.map((point, index) => ({ ...point, value: index ? 14 : 6 })) ?? null,
        },
    },
}
export const NotEnoughData: Story = {
    args: {
        progress: {
            ...reportCheckProgressFixture,
            status: 'insufficient_data',
            value: 0,
            sample_size: 0,
            explanation: 'No relevant activity was observed. Zero events alone cannot show whether the fix is working.',
            points: reportCheckProgressFixture.points?.map((point) => ({ ...point, value: 0 })) ?? null,
        },
    },
}
export const Rate: Story = {
    args: {
        metric: { ...reportMetricsFixture[0], title: 'Checkout failure rate', value_format: 'percentage', unit: null },
        progress: {
            ...reportCheckProgressFixture,
            target_type: 'fixed',
            value: 3,
            target: 5,
            sample_size: 200,
            explanation: 'Compared with the original rate or average target. This is a provisional assessment.',
            points: reportCheckProgressFixture.points?.map((point) => ({ ...point, target: 5 })) ?? null,
        },
    },
}
