import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { LabeledRow } from '../components/LabeledRow'
import { ObservationSignalReports } from './ObservationSignalReports'

const OBSERVATION_ID = '0199c0de-3333-7000-8000-0000000000c1'

const meta: Meta<typeof ObservationSignalReports> = {
    title: 'Scenes-App/Replay Vision/Observation signal reports',
    component: ObservationSignalReports,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof ObservationSignalReports>

function report(id: string, title: string | null, status: string): Record<string, any> {
    return { id, title, status, created_at: '2026-09-17T20:46:11Z' }
}

function mockReports(results: Record<string, any>[]): void {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/vision/observations/:id/signal_reports/': () => [200, results],
        },
    })
}

/** The row sits in a card of sibling rows, so the stories carry two of them for context. */
function Card({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="grid grid-cols-2 gap-3 max-w-2xl border rounded p-3 bg-surface-primary">
            <LabeledRow label="Score label">
                <span>Severity</span>
            </LabeledRow>
            <LabeledRow label="Scale maximum">
                <span>10</span>
            </LabeledRow>
            {children}
        </div>
    )
}

export const OneReport: Story = {
    render: () => {
        mockReports([report('r-1', 'fix: repair dead-end access-denied flow for new invitees', 'ready')])
        return (
            <Card>
                <ObservationSignalReports observationId={OBSERVATION_ID} signalsCount={1} />
            </Card>
        )
    },
}

export const SeveralReports: Story = {
    render: () => {
        mockReports([
            report('r-1', 'fix: repair dead-end access-denied flow for new invitees', 'ready'),
            report('r-2', 'feat: surface the retry control on a failed scan', 'in_progress'),
            report('r-3', null, 'potential'),
        ])
        return (
            <Card>
                <ObservationSignalReports observationId={OBSERVATION_ID} signalsCount={3} />
            </Card>
        )
    },
}

export const NoReportFound: Story = {
    render: () => {
        mockReports([])
        return (
            <Card>
                <ObservationSignalReports observationId={OBSERVATION_ID} signalsCount={2} />
            </Card>
        )
    },
}

export const NoSignalsEmitted: Story = {
    render: () => {
        mockReports([])
        return (
            <Card>
                <ObservationSignalReports observationId={OBSERVATION_ID} signalsCount={0} />
            </Card>
        )
    },
}

export const LookupFailed: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/vision/observations/:id/signal_reports/': () => [403, { detail: 'denied' }],
            },
        })
        return (
            <Card>
                <ObservationSignalReports observationId={OBSERVATION_ID} signalsCount={1} />
            </Card>
        )
    },
}
