import type { GoalScoutEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { latestValue, measureValue, money, shortDate } from '../../../../utils/goal/format'

export function GoalScoutLine({ goal }: { goal: GoalScoutEntryApi }): JSX.Element {
    const latest = latestValue(goal.metric)
    const comparison = goal.direction === 'decrease' ? '≤' : '≥'
    const value =
        latest === null
            ? goal.status === 'closed'
                ? 'not measured'
                : 'no data yet'
            : `${measureValue(latest.value, goal.unit)}${latest.stale && latest.date ? ` on ${shortDate(latest.date)}` : ''}`
    const target = goal.target !== null ? ` → ${comparison} ${measureValue(Number(goal.target), goal.unit)}` : ''
    const tests = goal.ideas_tried
        ? `${goal.ideas_tried} tested, ${goal.ideas_won} won`
        : goal.status === 'closed'
          ? 'No tests'
          : 'No tests yet'
    return (
        <>
            <p
                className={
                    goal.state.needs_you
                        ? 'm-0 text-xs leading-snug font-semibold text-warning'
                        : 'm-0 text-xs leading-snug text-secondary'
                }
            >
                {goal.state.headline}
            </p>
            <p className="m-0 mt-1 line-clamp-1 text-xs leading-none text-tertiary tabular-nums">
                {[
                    `${goal.goal_metric}: ${value}${target}`,
                    `${money(goal.money.spent_cents)} of ${money(goal.money.allocated_cents)}`,
                    tests,
                ].join(' · ')}
            </p>
        </>
    )
}
