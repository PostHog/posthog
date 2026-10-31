import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonBanner, LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'
import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlass)

const SEARCH_SOURCES = [
    { type: 'GoogleAds', name: 'Google Ads' },
    { type: 'BingAds', name: 'Bing Ads' },
    { type: 'GoogleSearchConsole', name: 'Google Search Console' },
]
const SEARCH_SOURCE_TYPES = SEARCH_SOURCES.map((source) => source.type)

export function SearchConsoleSource({ headerAction }: { headerAction?: ReactNode }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources } = useValues(marketingAnalyticsLogic)
    const { sourcesLoadError, dataWarehouseSourcesLoading } = useValues(sourcesDataLogic)
    const { loadSources } = useActions(sourcesDataLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    if (!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]) {
        return null
    }
    if (!dataWarehouseSources) {
        return (
            <section className="w-full mt-8 mb-6">
                <h2 className="mb-4 flex items-center justify-between gap-2">
                    <span>Search performance</span>
                    {headerAction}
                </h2>
                {sourcesLoadError ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Try again', onClick: loadSources, loading: dataWarehouseSourcesLoading }}
                    >
                        Could not check your search connections. Try again to load your sources.
                    </LemonBanner>
                ) : (
                    <LemonCard hoverEffect={false}>
                        <div className="flex items-start gap-4" role="status">
                            <Spinner className="mt-1 shrink-0" />
                            <div className="min-w-0 flex-1">
                                <h3 className="mb-2">Checking your search connections</h3>
                                <p className="text-secondary mb-0">Looking for connected search sources.</p>
                            </div>
                        </div>
                    </LemonCard>
                )}
            </section>
        )
    }
    // Once any search source is connected, the scene renders search performance, which suggests the missing ones.
    if (dataWarehouseSources.results.some((connection) => SEARCH_SOURCE_TYPES.includes(connection.source_type))) {
        return null
    }
    return (
        <section className="w-full mt-8 mb-6">
            <h2 className="mb-4">Search performance</h2>
            <LemonCard hoverEffect={false} className="space-y-4" data-attr="marketing-search-console-extra">
                <div className="flex items-start gap-4">
                    <div className="min-w-0 flex-1">
                        <h3 className="mb-2">Connect your search sources</h3>
                        <p className="text-secondary text-sm mb-0">
                            Google Search Console shows organic queries, landing pages and average positions. Connect
                            Google Ads or Bing Ads to compare paid keywords with organic queries and use spend and
                            conversion data to guide your search ad decisions.
                        </p>
                    </div>
                    <HedgehogMagnifyingGlass className="w-20 shrink-0" />
                    {headerAction}
                </div>
                <div className="divide-y">
                    {SEARCH_SOURCES.map((source) => (
                        <div key={source.type} className="flex flex-wrap items-center justify-between gap-3 py-2">
                            <div className="min-w-0 flex items-center gap-3">
                                <SourceIcon type={source.type} size="small" disableTooltip />
                                <strong>{source.name}</strong>
                            </div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                disabledReason={restrictedReason}
                                to={urls.dataWarehouseSourceNew(
                                    source.type,
                                    urls.marketingAnalyticsApp(),
                                    'Marketing analytics'
                                )}
                                targetBlank
                            >
                                Connect
                            </LemonButton>
                        </div>
                    ))}
                </div>
            </LemonCard>
        </section>
    )
}
