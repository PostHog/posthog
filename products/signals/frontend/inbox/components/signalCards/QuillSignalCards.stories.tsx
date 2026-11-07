import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import type { SignalNode } from 'scenes/debug/signals/types'

import { mswDecorator } from '~/mocks/browser'

import { QuillSignalCard } from '../../QuillSignalCard'
import {
    anomalyInvestigation,
    ciFlakyCheck,
    conversationsTicket,
    conversationsTicketWithoutNumber,
    endpointFailure,
    ERROR_TRACKING_ISSUE_MOCKS,
    errorTrackingIssue,
    errorTrackingIssueWithStackTrace,
    genericWithEntityLink,
    genericWithExternalLink,
    genericWithoutLink,
    githubIssue,
    healthCheck,
    linearIssue,
    logsAlert,
    pgAnalyzeIssue,
    scannerFinding,
    scoutFinding,
    scoutFindingWithLongName,
    sessionProblem,
    sessionProblemWithoutScreenshot,
    SIGNAL_CARD_MOCKS,
    zendeskTicket,
} from './signalCardStoryMocks'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Quill signal cards',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-06-11',
        featureFlags: { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true },
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [mswDecorator(SIGNAL_CARD_MOCKS)],
}
export default meta

type Story = StoryObj

const ALL_SOURCES = [
    scoutFinding,
    scannerFinding,
    sessionProblem,
    errorTrackingIssue,
    healthCheck,
    conversationsTicket,
    githubIssue,
    linearIssue,
    zendeskTicket,
    pgAnalyzeIssue,
    logsAlert,
    endpointFailure,
    ciFlakyCheck,
    anomalyInvestigation,
]

/** Same width as the evidence rail in the report detail, or a phone viewport when `phone` is set. */
function Rail({ signals, phone = false }: { signals: SignalNode[]; phone?: boolean }): JSX.Element {
    return (
        <div data-quill className={phone ? 'flex w-[22.5rem] flex-col gap-3' : 'flex w-[26rem] flex-col gap-3'}>
            {signals.map((signal) => (
                <QuillSignalCard key={signal.signal_id} signal={signal} />
            ))}
        </div>
    )
}

export const RecordingPreviews: Story = {
    render: () => <Rail signals={[sessionProblem, scannerFinding, sessionProblemWithoutScreenshot]} />,
}

export const TicketAttachments: Story = {
    render: () => <Rail signals={[conversationsTicket]} />,
}

export const TicketWithoutNumber: Story = {
    render: () => <Rail signals={[conversationsTicketWithoutNumber]} />,
}

export const GenericFallbacks: Story = {
    render: () => <Rail signals={[genericWithEntityLink, genericWithExternalLink, genericWithoutLink]} />,
}

/** The stack trace fence in the signal content is cut to three lines instead of filling the rail. */
export const ErrorTrackingStackTrace: Story = {
    decorators: [mswDecorator(ERROR_TRACKING_ISSUE_MOCKS)],
    render: () => <Rail signals={[errorTrackingIssueWithStackTrace]} />,
}

/** A scout name longer than the rail truncates, and the relative time stays at the end of the line. */
export const LongScoutName: Story = {
    render: () => <Rail signals={[scoutFindingWithLongName]} />,
}

/** One card per source with a dedicated renderer, so a layout change to any of them shows up here. */
export const AllSources: Story = {
    render: () => <Rail signals={ALL_SOURCES} />,
}

/** Every card at a 360px phone viewport: rows wrap and long strings truncate instead of scrolling sideways. */
export const AllSourcesPhoneWidth: Story = {
    render: () => <Rail signals={ALL_SOURCES} phone />,
}
