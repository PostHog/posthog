import { useValues } from 'kea'

import { DELIVERY_DATE_OPTIONS, ScopeDateFilter } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { DeliveryScope } from '../lib/deliveryScope'
import { DeliverySections } from './DeliverySections'
import { deliverySummaryLogic } from './deliverySummaryLogic'

export function TeamDeliveryPanel({ scope, sourceId }: { scope: DeliveryScope; sourceId: string | null }): JSX.Element {
    const { summary, summaryLoading } = useValues(deliverySummaryLogic({ scope, sourceId }))
    return (
        <ScopePanel busy={summaryLoading} controls={<ScopeDateFilter dateOptions={DELIVERY_DATE_OPTIONS} />}>
            {/* Without the members table a team matches no author, so every figure would be a false zero. */}
            {summary && !summary.has_membership_data ? (
                <div className="py-8 text-center text-sm text-secondary">
                    No team membership data. Sync the team members table on this GitHub source to see this team's
                    delivery figures.
                </div>
            ) : (
                <DeliverySections scope={scope} scopeLabel="This team" sourceId={sourceId} />
            )}
        </ScopePanel>
    )
}
