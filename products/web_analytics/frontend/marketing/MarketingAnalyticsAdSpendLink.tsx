import { useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { captureMarketingCrossSellClick } from 'lib/marketingCrossSell'
import { teamLogic } from 'scenes/teamLogic'
import {
    getEnabledNativeMarketingSources,
    nativeSourceDisplayLabel,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { DateRange, WebStatsBreakdown } from '~/queries/schema/schema-general'

import { AdPlatformLogo } from './AdPlatformLogo'
import { marketingCrossSellStateLogic } from './marketingCrossSellStateLogic'
import {
    buildMarketingAnalyticsDestination,
    isMarketingCrossSellTestArm,
    isMarketingSetupEnabled,
    paidTrafficTarget,
} from './marketingCrossSellUtils'

export interface MarketingAnalyticsAdSpendLinkProps {
    breakdownBy: WebStatsBreakdown
    value: string
    dateRange: DateRange | null | undefined
    children: React.ReactNode
}

export function MarketingAnalyticsAdSpendLink({
    breakdownBy,
    value,
    dateRange,
    children,
}: MarketingAnalyticsAdSpendLinkProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam, currentTeamId } = useValues(teamLogic)
    const { hasConnectedSources } = useValues(marketingCrossSellStateLogic({ teamId: currentTeamId ?? 0 }))

    const target =
        currentTeamId && isMarketingCrossSellTestArm(featureFlags)
            ? paidTrafficTarget(
                  breakdownBy,
                  value,
                  currentTeam?.marketing_analytics_config,
                  getEnabledNativeMarketingSources(featureFlags)
              )
            : null
    if (!currentTeamId || !target) {
        return <>{children}</>
    }
    const destination = buildMarketingAnalyticsDestination({
        hasConnectedSources,
        platform: target.platform,
        dateRange,
        setupEnabled: isMarketingSetupEnabled(featureFlags),
    })

    return (
        <span className="inline-flex items-center gap-2 whitespace-nowrap">
            {children}
            <Tooltip
                title={
                    target.platform
                        ? `See what ${nativeSourceDisplayLabel(target.platform)} cost and what it returned in Marketing analytics`
                        : 'See what this traffic cost and what it returned in Marketing analytics'
                }
            >
                <Link
                    to={destination}
                    className="inline-flex items-center gap-1 text-xs opacity-0 transition-opacity focus-visible:opacity-100 [[data-row-key]:hover_&]:opacity-100"
                    data-attr="web-analytics-marketing-cross-sell-row"
                    onClick={(e: React.MouseEvent) => {
                        e.stopPropagation()
                        captureMarketingCrossSellClick(currentTeamId, breakdownBy, hasConnectedSources, {
                            variant: 'row_action',
                            platform: target.platform,
                        })
                    }}
                >
                    {target.platform ? <AdPlatformLogo platform={target.platform} /> : null}
                    <span className="underline underline-offset-2">See ad spend</span>
                    <IconArrowRight className="shrink-0" />
                </Link>
            </Tooltip>
        </span>
    )
}
