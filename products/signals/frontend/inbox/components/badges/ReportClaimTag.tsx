import { useValues } from 'kea'

import { LemonTag, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { SignalReport } from '../../types'

/**
 * Marks a claimed report, so the list tells the user's own claims apart from a teammate's. A claim by
 * an MCP agent or an internal task counts for the person who answers for it.
 */
export function ReportClaimTag({ report }: { report: Pick<SignalReport, 'assignee'> }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const assignee = report.assignee
    const person = assignee?.responsible_user
    if (!assignee || !person) {
        return null
    }
    const isMine = !!user?.uuid && person.uuid === user.uuid
    const byAgent = assignee.kind !== 'user'
    const name = fullNameOrEmail(person)

    if (isMine) {
        return (
            <Tooltip title={byAgent ? 'One of your agents claimed this report' : 'You claimed this report'}>
                <LemonTag type="success" size="small" data-attr="inbox-report-card-claim-tag">
                    {byAgent ? 'Your agent is on it' : "You're on it"}
                </LemonTag>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={byAgent ? `${name}'s agent is working on this` : `${name} is working on this`}>
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
