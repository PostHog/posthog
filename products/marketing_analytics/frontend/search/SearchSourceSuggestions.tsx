import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { QuillSearchNotice } from './QuillSearchNotice'
import { SEARCH_PLATFORM_LABELS, SearchPlatform } from './searchPerformance'
import { searchPerformanceLogic } from './searchPerformanceLogic'

const connectUrl = (source: SearchPlatform): string =>
    urls.dataWarehouseSourceNew(
        source,
        `${urls.marketingAnalyticsApp()}?tab=search-performance`,
        'Marketing analytics',
        undefined,
        'marketing_analytics_search_suggestions'
    )

const suggestionMessage = (source: SearchPlatform): string =>
    source === 'GoogleAds'
        ? 'Connect Google Ads to see paid keywords, spend and conversions.'
        : 'Connect Google Search Console to see organic queries, landing pages and average positions.'

export function SearchSourceSuggestions(): JSX.Element {
    const { missingSources } = useValues(searchPerformanceLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    return (
        <>
            {missingSources.map((source) =>
                todayRailNav ? (
                    <QuillSearchNotice
                        key={source}
                        action={
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={<LinkPrimitive to={connectUrl(source)} />}
                                disabledReason={restrictedReason}
                            >
                                <SourceIcon type={source} size="xsmall" disableTooltip />
                                {`Connect ${SEARCH_PLATFORM_LABELS[source]}`}
                            </Button>
                        }
                    >
                        {suggestionMessage(source)}
                    </QuillSearchNotice>
                ) : (
                    <LemonBanner
                        key={source}
                        type="info"
                        action={{
                            children: `Connect ${SEARCH_PLATFORM_LABELS[source]}`,
                            icon: <SourceIcon type={source} size="xsmall" disableTooltip />,
                            disabledReason: restrictedReason,
                            to: connectUrl(source),
                        }}
                    >
                        {suggestionMessage(source)}
                    </LemonBanner>
                )
            )}
        </>
    )
}
