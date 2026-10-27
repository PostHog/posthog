import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import type { SignalReportAssigneeApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportActionability, SignalReportPriority, SignalReportStatus } from '../../types'
import { AnimatedEllipsis } from './AnimatedEllipsis'
import { ReportClaimTag } from './ReportClaimTag'
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

function userClaim(user: { id: number; uuid: string; first_name: string; email: string }): SignalReportAssigneeApi {
    return {
        claim_id: null,
        kind: 'user',
        user: { ...user, last_name: '' },
        task_id: null,
        agent: null,
        claimed_at: '2026-06-10T12:00:00Z',
    }
}

const MY_CLAIM = userClaim(MOCK_DEFAULT_USER)
const TEAMMATE_CLAIM = userClaim({ id: 2, uuid: 'teammate-uuid', first_name: 'Robin', email: 'robin@example.com' })

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
            <Row label="Claim">
                <ReportClaimTag report={{ assignee: MY_CLAIM }} />
                <ReportClaimTag report={{ assignee: TEAMMATE_CLAIM }} />
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
