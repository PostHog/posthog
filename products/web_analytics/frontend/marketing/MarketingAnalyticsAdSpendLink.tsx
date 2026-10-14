import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconArrowRight } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { captureMarketingCrossSellClick } from 'lib/marketingCrossSell'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
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
    const { location } = useValues(router)
    const { hasConnectedSources } = useValues(marketingCrossSellStateLogic({ teamId: currentTeamId ?? 0 }))
    const { ensureConnectionState } = useActions(marketingCrossSellStateLogic({ teamId: currentTeamId ?? 0 }))

    const candidate =
        currentTeamId &&
        removeProjectIdIfPresent(location.pathname) === urls.webAnalytics() &&
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL] === true
            ? paidTrafficTarget(
                  breakdownBy,
                  value,
                  currentTeam?.marketing_analytics_config,
                  getEnabledNativeMarketingSources(featureFlags)
              )
            : null
    const target = candidate && isMarketingCrossSellTestArm(featureFlags) ? candidate : null
    const hasTarget = !!target

    useEffect(() => {
        if (hasTarget) {
            ensureConnectionState()
        }
    }, [hasTarget, ensureConnectionState])

    if (!currentTeamId || !target || hasConnectedSources === null) {
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
