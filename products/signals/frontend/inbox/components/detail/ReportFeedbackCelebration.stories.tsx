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

/** The hog in its resting pose, anchored to a stand-in for the thumbs-up button. */
export const Resting: Story = {
    args: { onDone: () => {} },
    render: (args) => (
        <div className="flex h-[240px] w-[400px] items-end justify-center p-8">
            <span className="relative inline-flex">
                <span className="h-6 w-6 rounded border border-primary bg-surface-primary" />
                <ReportFeedbackCelebration {...args} />
            </span>
        </div>
    ),
}

/** The real footer, right-aligned as in the summary column, with the flag on: click the thumbs-up to see the hog pop. */
export const InFooter: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.INBOX_REPORT_FEEDBACK_BANG]: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports/:reportId/feedback_state/': { sentiment: null, note: '' },
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
        <div className="bg-primary flex min-h-[400px] items-start justify-center px-8 pt-40 pb-8">
            <div className="w-[32rem] border border-primary bg-surface-primary p-5">
                <ReportFeedbackFooter
                    report={makeReport({ title: 'Checkout errors spiked after the release' })}
                    align="end"
                />
            </div>
        </div>
    ),
}
