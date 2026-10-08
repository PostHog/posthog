import { useValues } from 'kea'
import { ReactNode } from 'react'

import { ScopePanel } from '../components/ScopePanel'
import { DeliveryScope } from '../lib/deliveryScope'
import { DeliverySections } from './DeliverySections'
import { deliverySummaryLogic } from './deliverySummaryLogic'

/** The team page's window panel with the team's delivery figures on top, so a delivery reload spins the rim too. */
export function TeamDeliveryPanel({
    scope,
    sourceId,
    busy,
    controls,
    children,
}: {
    scope: DeliveryScope
    sourceId: string | null
    busy: boolean
    controls: ReactNode
    children: ReactNode
}): JSX.Element {
    const { summary, summaryFailed, summaryLoading } = useValues(deliverySummaryLogic({ scope, sourceId }))

    return (
        <ScopePanel busy={busy || summaryLoading} controls={controls}>
            {summary && !summaryFailed && !summary.has_membership_data ? (
                // Without the members table a team matches no author, so every figure would be a false zero.
                <div className="py-8 text-center text-sm text-secondary">
                    No team membership data. Sync the team members table on this GitHub source to see this team's
                    delivery figures.
                </div>
            ) : (
                <DeliverySections scope={scope} scopeLabel="This team" sourceId={sourceId} />
            )}
            {children}
        </ScopePanel>
    )
}
