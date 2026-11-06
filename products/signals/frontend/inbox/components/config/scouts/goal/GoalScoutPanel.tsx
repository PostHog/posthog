import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'
import { GoalActivity } from './GoalActivity'
import { GoalIdeas } from './GoalIdeas'
import { GoalMetrics } from './GoalMetrics'
import { GoalProgress } from './GoalProgress'
import { GoalScoutFormModal } from './GoalScoutFormModal'
import { GoalStatus } from './GoalStatus'

export function GoalScoutPanel({ goalId }: { goalId: string }): JSX.Element {
    const { goal, goalLoading, error, activity, activityLoading, activityError, editOpen } = useValues(
        goalScoutLogic({ id: goalId })
    )
    const { loadGoal, loadActivity, setEditOpen } = useActions(goalScoutLogic({ id: goalId }))
    if (!goal) {
        return error ? (
            <div className="flex flex-wrap items-center gap-2 text-sm text-danger" role="alert">
                {error}
                <LemonButton size="small" type="secondary" loading={goalLoading} onClick={loadGoal}>
                    Try again
                </LemonButton>
            </div>
        ) : (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-16 w-full" />
                <LemonSkeleton className="h-28 w-full" />
            </div>
        )
    }
    return (
        <div
            className="grid min-w-0 grid-cols-1 gap-6 @5xl:grid-cols-[minmax(0,1fr)_18rem]"
            data-attr="goal-scout-panel"
        >
            <div className="flex min-w-0 flex-col gap-5">
                {error && (
                    <p role="alert" className="m-0 text-sm text-danger">
                        {error}
                    </p>
                )}
                <GoalStatus goal={goal} />
                <GoalMetrics goal={goal} />
                {!goal.results && <GoalIdeas goal={goal} />}
                <GoalProgress goal={goal} />
            </div>
            <aside className="flex min-w-0 flex-col gap-5">
                <GoalActivity
                    entries={activity}
                    loading={activityLoading}
                    error={activityError}
                    onRefresh={loadActivity}
                />
            </aside>
            {goal.is_owner && editOpen && (
                <GoalScoutFormModal isOpen goalId={goalId} onClose={() => setEditOpen(false)} />
            )}
        </div>
    )
}
