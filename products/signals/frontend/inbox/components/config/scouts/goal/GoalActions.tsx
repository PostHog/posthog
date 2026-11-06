import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'

export function GoalActions({ goalId }: { goalId: string }): JSX.Element | null {
    const { goal, busy, busyOperation } = useValues(goalScoutLogic({ id: goalId }))
    const { closeGoal, setEditOpen } = useActions(goalScoutLogic({ id: goalId }))
    if (!goal?.is_owner || goal.status === 'closed') {
        return null
    }
    const finished = goal.status === 'reached' || goal.status === 'spent'
    const busyReason = busy ? 'Saving a change' : undefined
    return (
        <>
            <LemonButton type="secondary" size="small" onClick={() => setEditOpen(true)} data-attr="goal-scout-edit">
                Edit goal
            </LemonButton>
            {finished ? (
                <LemonButton
                    type="primary"
                    size="small"
                    loading={busyOperation === 'close'}
                    disabledReason={busyOperation === 'close' ? undefined : busyReason}
                    onClick={closeGoal}
                    data-attr="goal-scout-close"
                >
                    Close goal
                </LemonButton>
            ) : (
                <LemonMenu
                    placement="bottom-end"
                    items={[
                        {
                            label: 'Close goal',
                            status: 'danger',
                            onClick: closeGoal,
                            disabledReason: busyReason,
                            'data-attr': 'goal-scout-close',
                        },
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconEllipsis />}
                        loading={busyOperation === 'close'}
                        aria-label="More goal actions"
                    />
                </LemonMenu>
            )}
        </>
    )
}
