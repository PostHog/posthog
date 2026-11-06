import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'

export function GoalDismissForm({ goalId, workId }: { goalId: string; workId: string }): JSX.Element {
    const { busy, busyOperation, dismissReason } = useValues(goalScoutLogic({ id: goalId }))
    const { dismissIdea, openDismiss, setDismissReason } = useActions(goalScoutLogic({ id: goalId }))
    const dismissing = busyOperation === `dismiss:${workId}`
    return (
        <form
            className="flex max-w-[72ch] flex-col gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                if (dismissReason.trim()) {
                    dismissIdea(workId, dismissReason)
                }
            }}
        >
            <LemonField.Pure label="Why dismiss this idea?" help="The scout reads this before it looks for new ideas.">
                <LemonInput
                    autoFocus
                    maxLength={1000}
                    value={dismissReason}
                    onChange={setDismissReason}
                    placeholder="For example, we tried this last quarter"
                />
            </LemonField.Pure>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    htmlType="submit"
                    size="small"
                    type="primary"
                    loading={dismissing}
                    disabledReason={
                        !dismissReason.trim()
                            ? 'Add a reason first'
                            : busy && !dismissing
                              ? 'Saving a change'
                              : undefined
                    }
                    data-attr="goal-idea-dismiss-confirm"
                >
                    Dismiss idea
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    disabledReason={dismissing ? 'Dismissing' : undefined}
                    onClick={() => openDismiss(null)}
                    data-attr="goal-idea-dismiss-cancel"
                >
                    Cancel
                </LemonButton>
            </div>
        </form>
    )
}
