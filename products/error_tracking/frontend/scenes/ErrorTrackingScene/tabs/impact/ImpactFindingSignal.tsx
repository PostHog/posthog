import type { ImpactFinding } from './impactFindings'
import { AudienceSlicesSignal } from './signals/AudienceSlicesSignal'
import { FiresOnLeaveSignal } from './signals/FiresOnLeaveSignal'
import { FlowDropSignal } from './signals/FlowDropSignal'
import { FunnelStepSignal } from './signals/FunnelStepSignal'
import { InflatedCountsSignal } from './signals/InflatedCountsSignal'
import { KnownPatternsSignal } from './signals/KnownPatternsSignal'
import { LostVisitorSignal } from './signals/LostVisitorSignal'
import { ManyAccountsSignal } from './signals/ManyAccountsSignal'
import { OneAccountSignal } from './signals/OneAccountSignal'
import { QuickLeaveSignal } from './signals/QuickLeaveSignal'
import { SessionOverlapSignal } from './signals/SessionOverlapSignal'
import { SupportTicketsSignal } from './signals/SupportTicketsSignal'
import { SuppressedEventsSignal } from './signals/SuppressedEventsSignal'

export function ImpactFindingSignal({ finding }: { finding: ImpactFinding }): JSX.Element {
    switch (finding.lens) {
        case 'flow_drop':
            return <FlowDropSignal issue={finding.issue} incident={finding.incident} />
        case 'funnel_step':
            return <FunnelStepSignal issue={finding.issue} incident={finding.incident} />
        case 'quick_leave':
            return (
                <QuickLeaveSignal
                    issue={finding.issue}
                    minPageSeconds={finding.minPageSeconds}
                    quickLeaveSeconds={finding.quickLeaveSeconds}
                />
            )
        case 'lost_visitor':
            return <LostVisitorSignal issue={finding.issue} />
        case 'suppressed_events':
            return <SuppressedEventsSignal issue={finding.issue} />
        case 'support_tickets':
            return <SupportTicketsSignal issue={finding.issue} baselinePer1k={finding.baselinePer1k} />
        case 'many_accounts':
            return <ManyAccountsSignal issue={finding.issue} groupLabel={finding.groupLabel} />
        case 'one_account':
            return <OneAccountSignal issue={finding.issue} />
        case 'audience_slices':
            return <AudienceSlicesSignal issue={finding.issue} />
        case 'related_issues':
            return <SessionOverlapSignal pair={finding.issue} />
        case 'fires_on_leave':
            return <FiresOnLeaveSignal issue={finding.issue} />
        case 'inflated_counts':
            return <InflatedCountsSignal issue={finding.issue} />
        case 'known_patterns':
            return (
                <KnownPatternsSignal
                    issue={finding.issue}
                    totalEvents={finding.totalEvents}
                    classes={finding.classes}
                />
            )
    }
}
