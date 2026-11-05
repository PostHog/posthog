import type { Meta, StoryObj } from '@storybook/react'

import { IdeaBriefingInbox } from './IdeaBriefingInbox'
import { IdeaBriefingReport } from './IdeaBriefingReport'
import { IdeaHomeExtendedInbox } from './IdeaHomeExtendedInbox'
import { IdeaHomeExtendedReport } from './IdeaHomeExtendedReport'
import { IdeaReaderInbox } from './IdeaReaderInbox'
import { IdeaReaderReport } from './IdeaReaderReport'
import { IdeaStagesInbox } from './IdeaStagesInbox'
import { IdeaStagesReport } from './IdeaStagesReport'

// Design exploration for a Today-style inbox. Static mock data, not wired into the app.
const meta: Meta = {
    title: 'Scenes-App/Inbox/Mockups/Today style',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // Mockups have no visual contract to protect, so the runner only checks that they render.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj

export const Idea1HomeExtendedInbox: Story = { render: () => <IdeaHomeExtendedInbox /> }
export const Idea1HomeExtendedReport: Story = { render: () => <IdeaHomeExtendedReport /> }
export const Idea2BriefingInbox: Story = { render: () => <IdeaBriefingInbox /> }
export const Idea2BriefingReport: Story = { render: () => <IdeaBriefingReport /> }
export const Idea3ReaderInbox: Story = { render: () => <IdeaReaderInbox /> }
export const Idea3ReaderReport: Story = { render: () => <IdeaReaderReport /> }
export const Idea3ReaderReportOnAPhone: Story = {
    render: () => <IdeaReaderReport />,
    decorators: [
        (Story) => (
            // Phone width, so the facts rail shows as a strip above the report.
            <div className="w-[390px] border-r">
                <Story />
            </div>
        ),
    ],
}
export const Idea4StagesInbox: Story = { render: () => <IdeaStagesInbox /> }
export const Idea4StagesReport: Story = { render: () => <IdeaStagesReport /> }
