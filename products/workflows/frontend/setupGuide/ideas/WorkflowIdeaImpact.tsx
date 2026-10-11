import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { WorkflowIdeaApi } from '../../generated/api.schemas'
import { EXAMPLE_LIFT, estimatedMonthlyCost, exampleExtraPerMonth } from './ideaCopy'

/** How many people an idea reaches, what a small lift would be worth, and what its emails cost. */
export function WorkflowIdeaImpact({ evidence }: { evidence: WorkflowIdeaApi['evidence'] }): JSX.Element {
    const extra = exampleExtraPerMonth(evidence)
    const cost = estimatedMonthlyCost(evidence.emails_per_month ?? 0)
    return (
        <div className="flex flex-col gap-1 rounded border bg-surface-secondary p-2 text-sm">
            <span>
                <strong translate="no">{humanFriendlyNumber(evidence.reachable_people)}</strong>{' '}
                {evidence.audience ?? 'people'} a month don't {evidence.goal ?? 'reach the goal'} within a week
                {evidence.baseline_rate !== null && ` (${Math.round(evidence.baseline_rate * 100)}% do today)`}.
            </span>
            {extra !== null && evidence.goal_unit && (
                <span className="text-secondary">
                    For example, if {Math.round(EXAMPLE_LIFT * 100)} in 100 of them {evidence.goal} after these emails,
                    that's about{' '}
                    <strong className="text-primary">
                        {humanFriendlyNumber(extra)} more {evidence.goal_unit}
                    </strong>{' '}
                    a month. Once it runs, PostHog shows the real number.
                </span>
            )}
            {evidence.emails_per_month ? (
                <span className="text-xs text-secondary">
                    About {humanFriendlyNumber(evidence.emails_per_month)} emails a month at today's volume,{' '}
                    {cost > 0
                        ? `roughly $${humanFriendlyNumber(cost)} a month on its own.`
                        : 'within the free emails each month on its own.'}
                </span>
            ) : null}
        </div>
    )
}
