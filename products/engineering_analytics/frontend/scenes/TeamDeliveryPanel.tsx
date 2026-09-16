// A team's delivery sections in their own panel. Delivery has its own window because the team page's
// test-health endpoints cap theirs at 30 days.

import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { ScopePanel } from '../components/ScopePanel'
import { DeliveryScope } from '../lib/deliveryScope'
import { DELIVERY_DATE_OPTIONS, DeliverySections } from './DeliverySections'
import { deliverySummaryLogic } from './deliverySummaryLogic'
import { SHARED_DEFAULT_DATE_FROM, engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'

export function TeamDeliveryPanel({ scope, sourceId }: { scope: DeliveryScope; sourceId: string | null }): JSX.Element {
    const { summaryLoading } = useValues(deliverySummaryLogic({ scope, sourceId }))
    const { dateFrom, dateTo } = useValues(engineeringAnalyticsFiltersLogic)
    const { setDateRange } = useActions(engineeringAnalyticsFiltersLogic)
    return (
        <ScopePanel
            busy={summaryLoading}
            controls={
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(from, to) => setDateRange(from ?? SHARED_DEFAULT_DATE_FROM, to ?? null)}
                    dateOptions={DELIVERY_DATE_OPTIONS}
                    size="small"
                />
            }
        >
            <DeliverySections scope={scope} scopeLabel="This team" sourceId={sourceId} />
        </ScopePanel>
    )
}
