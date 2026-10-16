import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { SupportTicketsIssue } from '../recommendations/types'
import type { ImpactFinding } from './impactFindings'
import { share } from './impactFormat'

const MAX_TICKET_LINKS = 3

// How many things a finding touched, in the unit its lens counts.
export interface ImpactReach {
    value: number
    unit: string
    detail?: string
    tickets: SupportTicketsIssue['ticket_refs']
}

export function findingReach(finding: ImpactFinding): ImpactReach {
    switch (finding.lens) {
        case 'flow_drop':
            return {
                value: finding.issue.exposed,
                unit: 'visits with this error',
                detail: `${share(finding.issue.exposed_finish_rate)} got through`,
                tickets: [],
            }
        case 'funnel_step':
            return {
                value: finding.issue.exposed,
                unit: 'visits with this error',
                detail: `${share(finding.issue.exposed_finish_rate)} took the next step`,
                tickets: [],
            }
        case 'quick_leave':
            return {
                value: finding.issue.pageviews,
                unit: 'pageviews',
                detail:
                    finding.issue.returned_rate !== null
                        ? `${share(finding.issue.returned_rate)} came back within a day`
                        : undefined,
                tickets: [],
            }
        case 'lost_visitor':
            return {
                value: finding.issue.pageviews,
                unit: 'pageviews',
                detail: `${humanFriendlyLargeNumber(finding.issue.lost)} with no return within a day`,
                tickets: [],
            }
        case 'suppressed_events':
            return { value: finding.issue.sessions, unit: 'sessions on the page', tickets: [] }
        case 'support_tickets':
            return {
                value: finding.issue.tickets,
                unit: finding.issue.tickets === 1 ? 'ticket' : 'tickets',
                tickets: (finding.issue.ticket_refs ?? []).slice(0, MAX_TICKET_LINKS),
            }
        case 'many_accounts':
            return {
                value: finding.issue.people,
                unit: 'people',
                detail: `${humanFriendlyLargeNumber(finding.issue.sessions)} sessions`,
                tickets: [],
            }
        case 'one_account':
            return {
                value: finding.issue.sessions,
                unit: 'sessions',
                detail: `${humanFriendlyLargeNumber(finding.issue.people)} people`,
                tickets: [],
            }
        case 'related_issues':
            return {
                value: finding.issue.both_sessions,
                unit: 'sessions with both',
                detail: `${humanFriendlyLargeNumber(finding.issue.shared_sessions)} within 5 seconds`,
                tickets: [],
            }
        case 'audience_slices':
        case 'fires_on_leave':
            return { value: finding.issue.sessions, unit: 'sessions', tickets: [] }
        case 'inflated_counts':
            return {
                value: finding.issue.sessions,
                unit: 'sessions',
                detail: `${humanFriendlyLargeNumber(finding.issue.occurrences)} events`,
                tickets: [],
            }
        case 'known_patterns':
            return {
                value: finding.issue.sessions,
                unit: 'sessions',
                detail: `${humanFriendlyLargeNumber(finding.issue.events)} events`,
                tickets: [],
            }
    }
}
