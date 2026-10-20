import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import {
    MarketingDashboardView,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    BREAKDOWN_LABELS,
    DASHBOARD_BREAKDOWNS,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'

import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { MarketingSectionSwitcher } from './MarketingSectionSwitcher'

function NavigationPreview(): JSX.Element {
    const { dashboardBreakdown, dashboardProperties } = useValues(marketingAnalyticsLogic)
    const { setDashboardBreakdown, setDashboardProperties } = useActions(marketingAnalyticsLogic)

    return (
        <div className="flex flex-col gap-4 w-full">
            <div className="flex">
                <MarketingSectionSwitcher />
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    aria-label="Breakdown"
                    value={dashboardBreakdown}
                    onChange={(value) => value && setDashboardBreakdown(value)}
                    options={DASHBOARD_BREAKDOWNS.map((value) => ({ value, label: BREAKDOWN_LABELS[value] }))}
                />
                <LemonButton
                    onClick={() =>
                        setDashboardProperties([
                            {
                                type: PropertyFilterType.Session,
                                key: '$channel_type',
                                operator: PropertyOperator.Exact,
                                value: 'Direct',
                            },
                        ])
                    }
                >
                    Filter direct traffic
                </LemonButton>
                <span>{`Active filters: ${dashboardProperties.length}`}</span>
            </div>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    to={`${urls.marketingAnalyticsApp()}?view=${MarketingDashboardView.RETENTION}&breakdown=${MarketingAnalyticsAttributionBreakdown.Source}`}
                >
                    Open retention link
                </LemonButton>
                <LemonButton to={urls.marketingAnalyticsApp()}>Open default link</LemonButton>
            </div>
        </div>
    )
}

const meta: Meta<typeof MarketingSectionSwitcher> = {
    title: 'Marketing Analytics/Dashboard/Section switcher',
    component: MarketingSectionSwitcher,
    parameters: {
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD],
        pageUrl: urls.marketingAnalyticsApp(),
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const InteractiveNavigation: Story = { render: () => <NavigationPreview /> }
export const Narrow: Story = {
    render: () => (
        <div className="w-[32.5rem] max-w-full">
            <MarketingSectionSwitcher />
        </div>
    ),
}
