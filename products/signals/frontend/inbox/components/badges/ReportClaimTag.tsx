import { useValues } from 'kea'

import { LemonTag, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { SignalReport } from '../../types'

function claimTooltip(kind: string, name: string | null): string {
    if (kind === 'agent') {
        return name ? `${name}'s agent is working on this` : 'Your agent is working on this'
    }
    if (kind === 'task') {
        return name ? `A task ${name} started is working on this` : 'A task you started is working on this'
    }
    return name ? `${name} is working on this` : 'You claimed this report'
}

/**
 * Marks a claimed report, so the list tells the user's own claims apart from a teammate's. A claim by
 * an MCP agent or an internal task counts for the person who answers for it, and the tooltip says which.
 */
export function ReportClaimTag({ report }: { report: Pick<SignalReport, 'assignee'> }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const assignee = report.assignee
    const person = assignee?.responsible_user
    if (!assignee || !person) {
        return null
    }
    const isMine = !!user?.uuid && person.uuid === user.uuid
    const name = fullNameOrEmail(person)

    if (isMine) {
        return (
            <Tooltip title={claimTooltip(assignee.kind, null)}>
                <LemonTag type="success" size="small" data-attr="inbox-report-card-claim-tag">
                    You're on it
                </LemonTag>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={claimTooltip(assignee.kind, name)}>
            <LemonTag
                size="small"
                icon={<ProfilePicture user={person} name={name} size="xs" />}
                data-attr="inbox-report-card-claim-tag"
            >
                <span className="max-w-32 truncate">{person.first_name || name}</span>
            </LemonTag>
        </Tooltip>
    )
}
