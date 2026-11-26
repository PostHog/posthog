import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { SignalReportStatus } from '../../types'
import { ReportPrMonitoringCard, ReportPrMonitoringCardProps } from './ReportPrMonitoringCard'

function StatefulCard(props: ReportPrMonitoringCardProps): JSX.Element {
    const [draftNote, setDraftNote] = useState(props.draftNote)
    return <ReportPrMonitoringCard {...props} draftNote={draftNote} onChangeNote={setDraftNote} />
}

const meta: Meta<typeof ReportPrMonitoringCard> = {
    title: 'Scenes-App/Signals/ReportPrMonitoringCard',
    component: ReportPrMonitoringCard,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        (Story) => (
            <div className="max-w-2xl p-4">
                <Story />
            </div>
        ),
    ],
    args: {
        status: SignalReportStatus.PENDING_INPUT,
        guidanceQuestion:
            'Coupon drawer dismissal has no dedicated event in this project. ' +
            'Candidate proxy events exist, including `checkout_started` and `cart_viewed`, ' +
            'which measure checkout entry rather than drawer interactions. Which event or action should PostHog watch after merge?',
        artefactsLoading: false,
        draftNote: '',
        submitting: false,
        hasResearchRun: true,
        onChangeNote: () => {},
        onSubmit: () => {},
        onViewResearchRun: () => {},
    },
    render: (args) => <StatefulCard {...args} />,
}

export default meta
type Story = StoryObj<typeof meta>

export const NeedsGuidance: Story = {}

export const NeedsGuidanceLoading: Story = {
    args: {
        guidanceQuestion: null,
        artefactsLoading: true,
    },
}

export const Researching: Story = {
    args: {
        status: SignalReportStatus.IN_PROGRESS,
        guidanceQuestion: null,
    },
}

export const Failed: Story = {
    args: {
        status: SignalReportStatus.FAILED,
        guidanceQuestion: null,
    },
}
