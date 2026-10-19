import { useActions, useValues } from 'kea'

import { IconTarget } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { marketingDashboardLogic } from '../marketingDashboardLogic'

/** The conversion goal the Overview and Conversion sections measure against. The icon carries the
 * meaning, so the control needs no label beside it. */
export function MarketingGoalSelect(): JSX.Element | null {
    const { conversionGoals, selectedConversionGoal } = useValues(marketingDashboardLogic)
    const { setConversionGoalId } = useActions(marketingDashboardLogic)

    if (!conversionGoals.length) {
        return null
    }

    return (
        <LemonSelect
            size="small"
            icon={<IconTarget />}
            value={selectedConversionGoal?.conversion_goal_id}
            onChange={(id) => id && setConversionGoalId(id)}
            options={conversionGoals.map((goal) => ({
                value: goal.conversion_goal_id,
                label: goal.conversion_goal_name,
            }))}
            dropdownMatchSelectWidth={false}
            aria-label="Conversion goal"
            // Inherited from the retired Revenue section's picker: a pinned wire string that
            // autocapture dashboards and Playwright already select on.
            data-attr="marketing-revenue-goal"
        />
    )
}
