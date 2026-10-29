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
    if (kind === 'task') {
        return name ? `A task ${name} started is working on this` : 'A task you started is working on this'
    }
    return name ? `${name} is working on this` : 'You claimed this report'
}

/**
 * Who answers for a report's claim, or null when nobody claimed it. A claim by an MCP agent or an
 * internal task counts for the person who answers for it, and the tooltip says which.
 */
export function useReportClaim(assignee: SignalReport['assignee']): ReportClaim | null {
    const { user } = useValues(userLogic)
    const person = assignee?.responsible_user
    if (!assignee || !person) {
        return null
    }
    const isMine = !!user?.uuid && person.uuid === user.uuid
    const name = fullNameOrEmail(person)
    return { person, name, isMine, tooltip: claimTooltip(assignee.kind, isMine ? null : name) }
}
