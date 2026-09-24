import { useActions, useValues } from 'kea'

import { IconCursor, IconPeople, IconPieChart, IconRetention, IconTarget } from '@posthog/icons'
import { LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import {
    MarketingDashboardView,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

const SECTIONS: { value: MarketingDashboardView; label: string; icon: JSX.Element }[] = [
    { value: MarketingDashboardView.OVERVIEW, label: 'Overview', icon: <IconPieChart /> },
    { value: MarketingDashboardView.ACQUISITION, label: 'Acquisition', icon: <IconPeople /> },
    { value: MarketingDashboardView.ENGAGEMENT, label: 'Engagement', icon: <IconCursor /> },
    { value: MarketingDashboardView.RETENTION, label: 'Retention', icon: <IconRetention /> },
    { value: MarketingDashboardView.CONVERSION, label: 'Conversion', icon: <IconTarget /> },
]

export function MarketingSectionSwitcher(): JSX.Element {
    const { dashboardView } = useValues(marketingAnalyticsLogic)
    const { setDashboardView } = useActions(marketingAnalyticsLogic)

    // Both controls render and a container query picks one, so the switch needs no measurement and
    // follows the space the header actually has rather than the window.
    return (
        <div className="@container flex-1 basis-56 min-w-0">
            <LemonSegmentedButton
                className="hidden @min-[36rem]:flex"
                size="small"
                value={dashboardView}
                onChange={(view) => setDashboardView(view)}
                options={SECTIONS.map((section) => ({
                    value: section.value,
                    label: section.label,
                    icon: section.icon,
                    'data-attr': `marketing-dashboard-section-${section.value}`,
                }))}
            />
            <LemonSelect
                className="@min-[36rem]:hidden"
                size="small"
                value={dashboardView}
                onChange={(view) => view && setDashboardView(view)}
                options={SECTIONS.map((section) => ({
                    value: section.value,
                    label: section.label,
                    icon: section.icon,
                }))}
                data-attr="marketing-dashboard-section-select"
                aria-label="Dashboard section"
            />
        </div>
    )
}
