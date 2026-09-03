import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { ReplayVisionScanWidget } from './ReplayVisionScanWidget'

const SCAN_ID = '0199c0de-1111-7000-8000-0000000000aa'
const SESSION_A = '0199c0de-2222-7000-8000-0000000000b1'
const SESSION_B = '0199c0de-2222-7000-8000-0000000000b2'
const SESSION_C = '0199c0de-2222-7000-8000-0000000000b3'

const meta: Meta<typeof ReplayVisionScanWidget> = {
    title: 'Scenes-App/Max AI/Replay Vision scan widget',
    component: ReplayVisionScanWidget,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof ReplayVisionScanWidget>

function observation(sessionId: string, status: string, modelOutput?: Record<string, unknown>): Record<string, any> {
    return {
        id: `obs-${sessionId}`,
        scanner_id: SCAN_ID,
        session_id: sessionId,
        status,
        error_reason: status === 'ineligible' ? 'too_short:the recording is under five seconds long' : '',
        scanner_result: modelOutput ? { model_output: modelOutput, signals_count: 0 } : null,
    }
}

function mockObservations(results: Record<string, any>[]): void {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/vision/scanners/:scanner_id/observations/': () => [200, { results }],
        },
    })
}

export const Running: Story = {
    render: () => {
        mockObservations([
            observation(SESSION_A, 'succeeded', {
                title: 'Abandoned checkout at the payment step',
                summary: 'The user retyped the card number four times, then closed the tab.',
            }),
            observation(SESSION_B, 'running'),
        ])
        return <ReplayVisionScanWidget scanId={SCAN_ID} sessionIds={[SESSION_A, SESSION_B]} skipped={[]} />
    },
    name: 'One finished, one still watching',
}

export const Finished: Story = {
    render: () => {
        mockObservations([
            observation(SESSION_A, 'succeeded', {
                title: 'Abandoned checkout at the payment step',
                summary: 'The user retyped the card number four times, then closed the tab.',
            }),
            observation(SESSION_B, 'ineligible'),
        ])
        return <ReplayVisionScanWidget scanId={SCAN_ID} sessionIds={[SESSION_A, SESSION_B]} skipped={[]} />
    },
    name: 'All recordings settled',
}

export const WithSkipped: Story = {
    render: () => {
        mockObservations([
            observation(SESSION_A, 'succeeded', {
                title: 'Completed signup without help',
                summary: 'The user filled the form once and reached the dashboard.',
            }),
        ])
        return (
            <ReplayVisionScanWidget
                scanId={SCAN_ID}
                sessionIds={[SESSION_A]}
                skipped={[
                    { sessionId: SESSION_B, reason: 'skipped_quota' },
                    { sessionId: SESSION_C, reason: 'skipped_quota' },
                ]}
            />
        )
    },
    name: 'Some recordings skipped',
}
