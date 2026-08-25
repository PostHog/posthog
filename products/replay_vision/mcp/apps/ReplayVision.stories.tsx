import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import {
    InlineScanView,
    type InlineScanData,
    VisionObservationListView,
    type VisionObservationData,
    type VisionObservationListData,
    VisionObservationView,
} from './index'

const meta: Meta = {
    title: 'MCP Apps/Replay Vision',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator has no dark mode, so a dark snapshot would just duplicate the light one.
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const scanStarted: InlineScanData = {
    started: 2,
    scan_id: '0199c0de-1111-7000-8000-0000000000aa',
    results: [
        { session_id: '0199c0de-2222-7000-8000-0000000000b1', scan_outcome: 'started' },
        { session_id: '0199c0de-2222-7000-8000-0000000000b2', scan_outcome: 'started' },
        { session_id: '0199c0de-2222-7000-8000-0000000000b3', scan_outcome: 'already_scanned' },
    ],
}

const scanOutOfCredits: InlineScanData = {
    started: 0,
    scan_id: null,
    results: [
        { session_id: '0199c0de-2222-7000-8000-0000000000b1', scan_outcome: 'skipped_quota' },
        { session_id: '0199c0de-2222-7000-8000-0000000000b2', scan_outcome: 'skipped_scanner_limit' },
    ],
}

export const ScanStarted: Story = {
    render: () => <InlineScanView data={scanStarted} />,
    name: 'Inline scan started',
}

export const ScanOutOfCredits: Story = {
    render: () => <InlineScanView data={scanOutOfCredits} />,
    name: 'Inline scan with nothing started',
}

const summarized: VisionObservationData = {
    id: '0199c0de-3333-7000-8000-0000000000c1',
    session_id: '0199c0de-2222-7000-8000-0000000000b1',
    status: 'succeeded',
    recording_subject_email: 'rider@example.com',
    scanner_result: {
        model_output: {
            title: 'Abandoned checkout at the payment step',
            summary:
                'The user browsed three product pages, added a jacket to the basket, and opened checkout. ' +
                'They filled in the shipping form, then switched to the payment tab and retyped the card ' +
                'number four times. Each attempt returned a validation message under the expiry field. ' +
                'They closed the tab without completing the order.',
        },
    },
}

const runningObservation: VisionObservationData = {
    id: '0199c0de-3333-7000-8000-0000000000c2',
    session_id: '0199c0de-2222-7000-8000-0000000000b2',
    status: 'running',
    scanner_result: null,
}

const ineligibleObservation: VisionObservationData = {
    id: '0199c0de-3333-7000-8000-0000000000c3',
    session_id: '0199c0de-2222-7000-8000-0000000000b3',
    status: 'ineligible',
    error_reason: 'too_short:the recording is under five seconds long',
    scanner_result: null,
}

const monitorObservation: VisionObservationData = {
    id: '0199c0de-3333-7000-8000-0000000000c4',
    session_id: '0199c0de-2222-7000-8000-0000000000b4',
    status: 'succeeded',
    scanner_result: {
        model_output: {
            verdict: 'yes',
            reasoning: 'The user opened the pricing page twice and never reached the signup form.',
        },
    },
}

export const SummarizedObservation: Story = {
    render: () => <VisionObservationView data={summarized} />,
    name: 'Observation with a summary',
}

export const IneligibleObservation: Story = {
    render: () => <VisionObservationView data={ineligibleObservation} />,
    name: 'Observation that could not be watched',
}

const observationList: VisionObservationListData = {
    count: 4,
    results: [summarized, monitorObservation, runningObservation, ineligibleObservation],
    _posthogUrl: 'https://us.posthog.com/project/1/replay-vision',
}

export const ObservationList: Story = {
    render: () => <VisionObservationListView data={observationList} />,
    name: 'Observation list',
}
