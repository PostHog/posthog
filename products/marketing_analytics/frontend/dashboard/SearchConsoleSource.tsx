import { useValues } from 'kea'

import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonButton, LemonCard, LemonTag, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlass)

export function SearchConsoleSource(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources } = useValues(marketingAnalyticsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    if (!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]) {
        return null
    }
    if (!dataWarehouseSources) {
        return (
            <section className="max-w-3xl w-full mx-auto mt-8 mb-6">
                <h2 className="mb-4">Search performance</h2>
                <LemonCard hoverEffect={false}>
                    <div className="flex items-start gap-4" role="status">
                        <Spinner className="mt-1 shrink-0" />
                        <div className="min-w-0 flex-1">
                            <h3 className="mb-2">Checking your search connections</h3>
                            <p className="text-secondary mb-0">Looking for connected search sources.</p>
                        </div>
                    </div>
                </LemonCard>
            </section>
        )
    }
    const sources = [
        { type: 'GoogleAds', name: 'Google Ads' },
        { type: 'BingAds', name: 'Bing Ads' },
        { type: 'GoogleSearchConsole', name: 'Google Search Console' },
    ].map((source) => ({
        ...source,
        connected: dataWarehouseSources?.results.some((connection) => connection.source_type === source.type),
    }))
    return (
        <section className="max-w-3xl w-full mx-auto mt-8 mb-6">
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
                </div>
                <div className="divide-y">
                    {sources.map((source) => (
                        <div key={source.type} className="flex flex-wrap items-center justify-between gap-3 py-2">
                            <div className="min-w-0 flex items-center gap-3">
                                <SourceIcon type={source.type} size="small" disableTooltip />
                                <strong>{source.name}</strong>
                                {source.connected && <LemonTag type="info">Connected</LemonTag>}
                            </div>
                            {!source.connected && (
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
                            )}
                        </div>
                    ))}
                </div>
            </LemonCard>
        </section>
    )
}
