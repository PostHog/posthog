import type { Meta, StoryObj } from '@storybook/react'

import { ReportFeedbackBang } from './ReportFeedbackBang'

const meta: Meta<typeof ReportFeedbackBang> = {
    title: 'Scenes-App/Inbox/ReportFeedbackBang',
    component: ReportFeedbackBang,
    parameters: { layout: 'fullscreen' },
    args: { origin: { x: 320, y: 300 }, onDone: () => {} },
}
export default meta

type Story = StoryObj<typeof ReportFeedbackBang>

/** The burst in its resting pose, anchored where a thumbs-up button would sit. */
export const Burst: Story = {
    render: (args) => (
        <div className="relative h-[400px] w-[640px]">
            <div className="absolute left-[308px] top-[300px] h-6 w-6 rounded border border-primary bg-surface-primary" />
            <ReportFeedbackBang {...args} />
        </div>
    ),
}
