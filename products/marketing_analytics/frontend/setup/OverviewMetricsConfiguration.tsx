import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import {
    OVERVIEW_METRIC_LABELS,
    OVERVIEW_METRIC_SLOTS,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { MarketingAnalyticsOverviewMetric } from '~/queries/schema/schema-general'

const SLOT_OPTIONS = OVERVIEW_METRIC_SLOTS.map((slot) =>
    slot.options.map((metric) => ({ value: metric, label: OVERVIEW_METRIC_LABELS[metric] }))
)

export function OverviewMetricsConfiguration(): JSX.Element {
    const { overviewMetrics } = useValues(marketingAnalyticsSettingsLogic)
    const { updateOverviewMetrics } = useActions(marketingAnalyticsSettingsLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const disabledReason = restrictionReason ?? (currentTeamLoading ? 'Saving' : undefined)

    const setSlot = (index: number, metric: MarketingAnalyticsOverviewMetric): void =>
        updateOverviewMetrics(overviewMetrics.map((current, at) => (at === index ? metric : current)))

    return (
        <div className="flex flex-col gap-3 max-w-xl">
            <div className="grid grid-cols-1 @md:grid-cols-2 gap-3">
                {OVERVIEW_METRIC_SLOTS.map((slot, index) => (
                    <LemonField.Pure key={slot.label} label={slot.label}>
                        <LemonSelect
                            value={overviewMetrics[index]}
                            onChange={(metric) => setSlot(index, metric)}
                            options={SLOT_OPTIONS[index]}
                            disabledReason={disabledReason}
                            data-attr={`marketing-overview-metric-${slot.label.toLowerCase()}`}
                            fullWidth
                        />
                    </LemonField.Pure>
                ))}
            </div>
            <p className="text-secondary text-xs mb-0">
                The Overview shows one card per group, in this order. Other can be any metric.
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
