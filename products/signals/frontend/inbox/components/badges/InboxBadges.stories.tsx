import type { Meta, StoryObj } from '@storybook/react'

import { SignalReportActionability, SignalReportPriority, SignalReportStatus } from '../../types'
import { AnimatedEllipsis } from './AnimatedEllipsis'
import { SignalReportActionabilityBadge } from './SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from './SignalReportPriorityBadge'
import { SignalReportStatusBadge } from './SignalReportStatusBadge'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Badges',
    parameters: { layout: 'centered', viewMode: 'story', mockDate: '2026-06-11' },
}
export default meta

type Story = StoryObj

const PRIORITIES: SignalReportPriority[] = ['P0', 'P1', 'P2', 'P3', 'P4']
const STATUSES = Object.values(SignalReportStatus)
const ACTIONABILITIES: SignalReportActionability[] = [
    'immediately_actionable',
    'requires_human_input',
    'not_actionable',
]

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-xs text-tertiary">{label}</span>
            <div className="flex items-center gap-2 flex-wrap">{children}</div>
        </div>
    )
}

export const AllBadges: Story = {
    render: () => (
        <div className="bg-primary p-8 flex flex-col gap-4">
            <Row label="Priority">
                {PRIORITIES.map((p) => (
                    <SignalReportPriorityBadge key={p} priority={p} />
                ))}
            </Row>
            <Row label="Status">
                {STATUSES.map((s) => (
                    <SignalReportStatusBadge key={s} status={s} />
                ))}
            </Row>
            <Row label="Actionability">
                {ACTIONABILITIES.map((a) => (
                    <SignalReportActionabilityBadge key={a} actionability={a} />
                ))}
            </Row>
            <Row label="Working">
                <span className="text-sm text-secondary">
                    Investigating
                    <AnimatedEllipsis />
                </span>
            </Row>
        </div>
    ),
}
