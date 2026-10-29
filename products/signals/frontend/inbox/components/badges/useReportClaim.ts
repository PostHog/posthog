import { useValues } from 'kea'

import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { SignalReport } from '../../types'

type ClaimPerson = NonNullable<NonNullable<SignalReport['assignee']>['responsible_user']>

export interface ReportClaim {
    person: ClaimPerson
    name: string
    isMine: boolean
    tooltip: string
}

function claimTooltip(kind: string, name: string | null): string {
    if (kind === 'agent') {
        return name ? `${name}'s agent is working on this` : 'Your agent is working on this'
    }
    return name ? `${name} is working on this` : 'You claimed this report'
}

/**
 * Who is working on a report, or null when no person claimed it. A claim by an MCP agent counts for
 * the person who directed it. An internal task claim shows nothing: auto-start runs tasks as a suggested
 * reviewer, so naming that person would claim work they never took on.
 */
export function useReportClaim(assignee: SignalReport['assignee']): ReportClaim | null {
    const { user } = useValues(userLogic)
    const person = assignee?.responsible_user
    if (!assignee || !person || assignee.kind === 'task') {
        return null
    }
    const isMine = !!user?.uuid && person.uuid === user.uuid
    const name = fullNameOrEmail(person)
    return { person, name, isMine, tooltip: claimTooltip(assignee.kind, isMine ? null : name) }
}
