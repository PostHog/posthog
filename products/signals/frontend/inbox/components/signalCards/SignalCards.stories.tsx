import type { Meta, StoryObj } from '@storybook/react'

import type { SignalNode } from 'scenes/debug/signals/types'

import { mswDecorator } from '~/mocks/browser'

import { SignalCard } from '../../SignalCard'
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
    title: 'Scenes-App/Inbox/Signal cards',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-06-11',
    },
    decorators: [mswDecorator(SIGNAL_CARD_MOCKS)],
}
export default meta

type Story = StoryObj

/** Same width as the evidence rail in the report detail, where these cards render. */
function Rail({ signals }: { signals: SignalNode[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-3 w-[26rem]">
            {signals.map((signal) => (
                <SignalCard key={signal.signal_id} signal={signal} />
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
    render: () => (
        <Rail
            signals={[
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
            ]}
        />
    ),
}
