import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { nativeSourceDisplayLabel } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import { AdPlatformLogo } from './AdPlatformLogo'
import { MarketingPaidTrafficCardLogicProps, marketingPaidTrafficCardLogic } from './marketingPaidTrafficCardLogic'

export function MarketingAnalyticsPaidTrafficCard({
    breakdown,
    ...props
}: MarketingPaidTrafficCardLogicProps & { breakdown: WebStatsBreakdown }): JSX.Element | null {
    const { paidTraffic, platformsResolved, platforms, primaryPlatform, platformDestination, allPlatformsDestination } =
        useValues(marketingPaidTrafficCardLogic(props))
    const { clickThrough, dismissCard } = useActions(marketingPaidTrafficCardLogic(props))

    if (!platformsResolved || !paidTraffic) {
        return null
    }
    const visitors = `${humanFriendlyNumber(paidTraffic.paidVisitors)} visitors`
    const origin =
        platforms.length > 0
            ? `${visitors}, mostly from ${platforms.slice(0, 2).map(nativeSourceDisplayLabel).join(' and ')}.`
            : `${visitors}.`
    const title = `${Math.max(1, Math.round(paidTraffic.share * 100))}% of your visitors came from paid ads`
    const description = `${origin} Connect your ad accounts to see what they cost and what they returned.`

    return (
        <div
            className="relative border-t px-4 py-3 pr-10 bg-surface-secondary rounded-b"
            data-attr="web-analytics-marketing-cross-sell-v2"
        >
            <div className="flex min-w-0 flex-col gap-2">
                <div>
                    <div className="font-semibold">{title}</div>
                    <div className="text-xs text-secondary">{description}</div>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {primaryPlatform ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<AdPlatformLogo platform={primaryPlatform} />}
                            to={platformDestination}
                            data-attr="web-analytics-marketing-cross-sell-connect-platform"
                            onClick={() => clickThrough(breakdown, primaryPlatform)}
                        >
                            {`Connect ${nativeSourceDisplayLabel(primaryPlatform)}`}
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        type={primaryPlatform ? 'tertiary' : 'primary'}
                        size="small"
                        to={allPlatformsDestination}
                        data-attr="web-analytics-marketing-cross-sell-all-platforms"
                        onClick={() => clickThrough(breakdown, null)}
                    >
                        {primaryPlatform ? 'Other platforms' : 'Connect ad accounts'}
                    </LemonButton>
                </div>
            </div>
            <LemonButton
                className="absolute top-2 right-2"
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                tooltip="Not now"
                aria-label="Not now"
                data-attr="web-analytics-marketing-cross-sell-snooze"
                onClick={dismissCard}
            />
        </div>
    )
}
