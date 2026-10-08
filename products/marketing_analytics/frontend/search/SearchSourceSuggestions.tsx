import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { urls } from 'scenes/urls'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { SEARCH_PLATFORM_LABELS } from './searchPerformance'
import { searchPerformanceLogic } from './searchPerformanceLogic'

export function SearchSourceSuggestions(): JSX.Element {
    const { missingSources } = useValues(searchPerformanceLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    return (
        <>
            {missingSources.map((source) => (
                <LemonBanner
                    key={source}
                    type="info"
                    action={{
                        children: `Connect ${SEARCH_PLATFORM_LABELS[source]}`,
                        icon: <SourceIcon type={source} size="xsmall" disableTooltip />,
                        disabledReason: restrictedReason,
                        to: urls.dataWarehouseSourceNew(
                            source,
                            `${urls.marketingAnalyticsApp()}?tab=ad-performance`,
                            'Marketing analytics'
                        ),
                    }}
                >
                    {source === 'GoogleAds'
                        ? 'Connect Google Ads to see paid keywords, spend and conversions.'
                        : 'Connect Google Search Console to see organic queries, landing pages and average positions.'}
                </LemonBanner>
            ))}
        </>
    )
}
