import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { inboxUsageLogic } from '../../logics/inboxUsageLogic'
import { InboxUsageWidget } from '../shell/InboxUsageWidget'
import { UsageOverview } from '../spend/UsageOverview'

export function SelfDrivingUsageSetting(): JSX.Element {
    const usageEnabled = useFeatureFlag('SELF_DRIVING_USAGE_DISPLAY')
    const { product: inboxUsageProduct, spendProduct, isLoading: inboxUsageLoading } = useValues(inboxUsageLogic)
    const showBillingUsage = inboxUsageProduct != null || spendProduct != null || inboxUsageLoading

    if (!showBillingUsage && !usageEnabled) {
        return <p className="m-0 text-secondary">No usage to show for this project yet.</p>
    }

    return (
        <div className="flex flex-col gap-3 max-w-4xl">
            {showBillingUsage && (
                <>
                    <p className="m-0 text-xs leading-snug text-secondary">
                        {spendProduct
                            ? 'Recorded billable usage this billing period.'
                            : 'Pull requests agents opened this billing period.'}
                    </p>
                    <InboxUsageWidget />
                </>
            )}
            {usageEnabled && (
                <div className={showBillingUsage ? 'border-t border-primary pt-3' : undefined}>
                    <div className="mb-3 flex flex-col gap-0.5">
                        <h4 className="m-0 text-sm font-semibold text-default">Usage breakdown</h4>
                        <p className="m-0 max-w-2xl text-xs leading-snug text-secondary">
                            Recorded usage for scout runs started and signals received in the last 30 days.
                        </p>
                    </div>
                    <UsageOverview />
                </div>
            )}
        </div>
    )
}
