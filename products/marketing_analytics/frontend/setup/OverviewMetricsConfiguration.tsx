import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import {
    DEFAULT_OVERVIEW_METRICS,
    OVERVIEW_METRIC_LABELS,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsOverviewMetric } from '~/queries/schema/schema-general'

const OPTIONS = DEFAULT_OVERVIEW_METRICS.map((metric) => ({
    key: metric,
    label: OVERVIEW_METRIC_LABELS[metric],
}))

export function OverviewMetricsConfiguration(): JSX.Element {
    const { overviewMetrics } = useValues(marketingAnalyticsSettingsLogic)
    const { updateOverviewMetrics } = useActions(marketingAnalyticsSettingsLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const disabledReason = restrictionReason ?? (currentTeamLoading ? 'Saving' : undefined)

    return (
        <div className="flex flex-col gap-3 max-w-xl">
            <LemonInputSelect
                mode="multiple"
                allowCustomValues={false}
                value={overviewMetrics}
                onChange={(metrics) => updateOverviewMetrics(metrics as MarketingAnalyticsOverviewMetric[])}
                options={OPTIONS}
                placeholder="Select metrics"
                disabledReason={disabledReason}
                data-attr="marketing-overview-metrics-select"
            />
            <p className="text-secondary text-xs mb-0">
                Cards appear in the order you select them. Clear every card to go back to the default set.
            </p>
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => updateOverviewMetrics([])}
                    disabledReason={disabledReason}
                    data-attr="marketing-overview-metrics-reset"
                >
                    Reset to default
                </LemonButton>
            </div>
        </div>
    )
}
