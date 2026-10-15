import { LemonBanner, LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { InsightDetails } from 'lib/components/Cards/InsightCard/InsightDetails'
import { urls } from 'scenes/urls'

import { DashboardFilter, HogQLVariable, Node, TileFilters } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

export interface InsightDashboardFiltersBannerProps {
    query: Node | null
    insightId: string
    dashboardId?: number
    filtersOverride?: DashboardFilter
    variablesOverride?: Record<string, HogQLVariable>
    tileFiltersOverride?: TileFilters | null
}

export function InsightDashboardFiltersBanner({
    query,
    insightId,
    dashboardId,
    filtersOverride,
    variablesOverride,
    tileFiltersOverride,
}: InsightDashboardFiltersBannerProps): JSX.Element {
    return (
        <LemonBanner type="info" className="mb-4" alignItems="start">
            <div className="space-y-2 font-normal">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 basis-80">
                        <div className="font-semibold">Dashboard filters applied</div>
                        <p className="mb-0">
                            These filters change this view, but do not change the saved insight. Discard them to restore
                            the saved settings and edit the insight.
                        </p>
                    </div>
                    <LemonButton type="secondary" to={urls.insightView(insightId as InsightShortId, dashboardId)}>
                        Discard dashboard filters
                    </LemonButton>
                </div>
                <LemonCollapse
                    embedded
                    defaultActiveKey="filters"
                    panels={[
                        {
                            key: 'filters',
                            header: 'Applied filters and saved settings',
                            content: (
                                <InsightDetails
                                    query={query}
                                    filtersOverride={filtersOverride}
                                    variablesOverride={variablesOverride}
                                    tileFiltersOverride={tileFiltersOverride}
                                />
                            ),
                        },
                    ]}
                />
            </div>
        </LemonBanner>
    )
}
