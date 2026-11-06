import { useActions, useValues } from 'kea'

import { IconLightBulb } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'

export function GoalAddIdeaForm({ goalId }: { goalId: string }): JSX.Element {
    const { busy, busyOperation, ideaDraft } = useValues(goalScoutLogic({ id: goalId }))
    const { addIdea, setAddingIdea, setIdeaDraft } = useActions(goalScoutLogic({ id: goalId }))
    const adding = busyOperation === 'add-idea'
    const empty = !ideaDraft.trim()
    return (
        <form
            className="flex flex-col gap-1.5 rounded border border-secondary bg-surface-primary py-2.5 ps-3 pe-3 @md:ps-9"
            onSubmit={(event) => {
                event.preventDefault()
                if (!empty) {
                    addIdea(ideaDraft)
                }
            }}
            onKeyDown={(event) => {
                if (event.key === 'Escape' && !adding) {
                    setAddingIdea(false)
                }
            }}
            data-attr="goal-add-idea-form"
        >
            <div className="flex flex-wrap items-center gap-2">
                <IconLightBulb className="size-4 shrink-0 text-warning" />
                <LemonInput
                    className="min-w-40 flex-1"
                    autoFocus
                    maxLength={255}
                    value={ideaDraft}
                    onChange={setIdeaDraft}
                    placeholder="Describe a change you want to test"
                    aria-label="Your idea"
                    size="small"
                />
                <LemonButton
                    htmlType="submit"
                    size="small"
                    type="primary"
                    loading={adding}
                    disabledReason={empty ? 'Describe the idea first' : busy && !adding ? 'Saving a change' : undefined}
                    data-attr="goal-add-idea-submit"
                >
                    Add idea
                </LemonButton>
                <LemonButton
                    size="small"
                    type="tertiary"
                    disabledReason={adding ? 'Adding the idea' : undefined}
                    onClick={() => setAddingIdea(false)}
                    data-attr="goal-add-idea-cancel"
                >
                    Cancel
                </LemonButton>
            </div>
            <span className="text-xs text-tertiary @md:ps-6">
                The scout checks it against your data before you choose.
            </span>
        </form>
    )
}
