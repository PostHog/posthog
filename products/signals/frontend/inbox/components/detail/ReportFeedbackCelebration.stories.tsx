import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { makeReport } from '../../__mocks__/inboxMocks'
import { ReportFeedbackCelebration } from './ReportFeedbackCelebration'
import { ReportFeedbackFooter } from './ReportFeedbackFooter'

const meta: Meta<typeof ReportFeedbackCelebration> = {
    title: 'Scenes-App/Inbox/ReportFeedbackCelebration',
    component: ReportFeedbackCelebration,
    parameters: { layout: 'fullscreen' },
}
export default meta

type Story = StoryObj<typeof ReportFeedbackCelebration>

/** The hog in its resting pose, anchored where a thumbs-up button would sit. */
export const Resting: Story = {
    args: { origin: { x: 320, y: 300 }, onDone: () => {} },
    render: (args) => (
        <div className="relative h-[400px] w-[640px]">
            <div className="absolute left-[308px] top-[300px] h-6 w-6 rounded border border-primary bg-surface-primary" />
            <ReportFeedbackCelebration {...args} />
        </div>
    ),
}

/** The real footer with the flag on: click the thumbs-up to see the hog pop. */
export const InFooter: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.INBOX_REPORT_FEEDBACK_BANG]: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports/:reportId/artefacts': { results: [] },
                '/api/projects/:id/signals/reports/:reportId/signals': { signals: [] },
                '/api/projects/:id/signals/reports/available_reviewers': [],
                '/api/projects/:id/signals/reports/:reportId/checks/': { results: [] },
            },
            post: {
                '/api/projects/:id/signals/reports/:reportId/feedback': { forwarded: false },
            },
        }),
    ],
    render: () => (
        <div className="bg-primary flex min-h-[400px] items-end justify-center p-8">
            <div className="w-[32rem] border border-primary bg-surface-primary p-5">
                <ReportFeedbackFooter report={makeReport({ title: 'Checkout errors spiked after the release' })} />
            </div>
        </div>
    ),
}
