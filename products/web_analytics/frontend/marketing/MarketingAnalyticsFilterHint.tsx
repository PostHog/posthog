import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { nativeSourceDisplayLabel } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { AdPlatformLogo } from './AdPlatformLogo'
import { marketingFilterHintLogic } from './marketingFilterHintLogic'

export function MarketingAnalyticsFilterHint({ teamId }: { teamId: number }): JSX.Element | null {
    const { visible, target, destination, hasConnectedSources } = useValues(marketingFilterHintLogic({ teamId }))
    const { dismiss, clickThrough } = useActions(marketingFilterHintLogic({ teamId }))

    if (!visible || !target) {
        return null
    }
    const platformName = target.platform ? nativeSourceDisplayLabel(target.platform) : null

    return (
        <LemonBanner
            type="info"
            icon={target.platform ? <AdPlatformLogo platform={target.platform} size="medium" /> : undefined}
            onClose={dismiss}
            action={{
                children:
                    platformName && hasConnectedSources === false
                        ? `Connect ${platformName}`
                        : 'Open Marketing analytics',
                to: destination,
                onClick: clickThrough,
                'data-attr': 'web-analytics-marketing-cross-sell-filter-hint-open',
            }}
        >
            {`You're viewing ${platformName ? `${platformName} traffic` : 'paid ad traffic'}. See what it cost and what it returned in Marketing analytics.`}
        </LemonBanner>
    )
}
