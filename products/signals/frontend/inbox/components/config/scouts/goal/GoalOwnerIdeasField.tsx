import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import { MAX_OWNER_IDEAS } from '../../../../utils/goal/form'

export function GoalOwnerIdeasField(): JSX.Element {
    const { goalForm } = useValues(goalScoutFormLogic)
    const { addOwnerIdea, changeOwnerIdea, removeOwnerIdea } = useActions(goalScoutFormLogic)
    const ideas = goalForm.ideas
    const lastEmpty = ideas.length > 0 && !ideas.at(-1)?.trim()

    return (
        <LemonField.Pure label={<span className="sr-only">Your ideas</span>}>
            <div className="flex flex-col gap-2">
                {ideas.length > 0 && (
                    <ol className="m-0 flex list-none flex-col gap-2 p-0">
                        {ideas.map((idea, index) => (
                            <li key={index} className="flex items-center gap-2">
                                <LemonInput
                                    className="flex-1"
                                    maxLength={255}
                                    value={idea}
                                    autoFocus={index === ideas.length - 1 && !idea}
                                    onChange={(value) => changeOwnerIdea(index, value)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' && !lastEmpty && ideas.length < MAX_OWNER_IDEAS) {
                                            event.preventDefault()
                                            addOwnerIdea()
                                        }
                                    }}
                                    placeholder="For example, show shipping costs on the product page"
                                    aria-label={`Idea ${index + 1}`}
                                />
                                {(ideas.length > 1 || !!idea.trim()) && (
                                    <LemonButton
                                        icon={<IconX />}
                                        tooltip="Remove idea"
                                        aria-label={`Remove idea ${index + 1}`}
                                        onClick={() => removeOwnerIdea(index)}
                                        data-attr="goal-scout-form-remove-idea"
                                    />
                                )}
                            </li>
                        ))}
                    </ol>
                )}
                {ideas.length < MAX_OWNER_IDEAS && !lastEmpty && (
                    <div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={addOwnerIdea}
                            data-attr="goal-scout-form-add-idea"
                        >
                            {ideas.some((idea) => idea.trim()) ? 'Add another idea' : 'Add an idea'}
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonField.Pure>
    )
}
