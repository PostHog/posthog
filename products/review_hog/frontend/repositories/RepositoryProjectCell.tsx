import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { projectName } from './repositoryChoices'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { RuleControls } from './RuleControls'

/** The project side of one repository: the rule it follows, and its exception if it has one. */
export function RepositoryProjectCell({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { addException, clearException, setExceptionFlashFor, addExceptionPerson, removeExceptionPerson } =
        useActions(reviewHogRepositoriesLogic)

    const name = entry.full_name
    const savingReason = busyRepositories.includes(name) ? 'Saving…' : undefined

    let content: JSX.Element
    if (entry.owner === 'other_project') {
        content = <span className="text-xs text-secondary">Reviewed in {projectName(entry.owner_project)}</span>
    } else if (!entry.in_project) {
        content = <span className="text-xs text-secondary">Not part of this project</span>
    } else if (entry.exception === null) {
        content = (
            <>
                <span className="text-xs text-secondary">Project rule</span>
                {canEdit && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconPlus />}
                        tooltip="Add an exception, starting from the project rule"
                        aria-label={`Add exception for ${name}`}
                        onClick={() => addException(entry)}
                        disabledReason={savingReason}
                        data-attr="review-hog-repository-add-exception"
                    >
                        Exception
                    </LemonButton>
                )}
            </>
        )
    } else {
        content = (
            <div className="flex min-w-0 flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonTag type="warning" size="small">
                        Exception
                    </LemonTag>
                    {canEdit && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            tooltip="Clear the exception and follow the project rule again"
                            aria-label={`Clear exception for ${name}`}
                            onClick={() => clearException(entry)}
                            disabledReason={savingReason}
                            data-attr="review-hog-repository-clear-exception"
                        >
                            Clear
                        </LemonButton>
                    )}
                </div>
                <RuleControls
                    label={`Exception for ${name}`}
                    flashFor={entry.exception.flash_for}
                    people={entry.exception.people}
                    canEdit={canEdit}
                    disabledReason={canEdit ? savingReason : 'Only project admins can change this'}
                    onChangeFlashFor={(flashFor) => setExceptionFlashFor(entry, flashFor)}
                    onAddPerson={(userId, kind) => addExceptionPerson(entry, userId, kind)}
                    onRemovePerson={(person) => removeExceptionPerson(entry, person)}
                    dataAttr="review-hog-repository-flash-for"
                />
            </div>
        )
    }

    return (
        <div className="flex min-h-8 min-w-0 flex-wrap items-center gap-2">
            <span className="text-xs text-secondary @min-[48rem]:hidden">Project:</span>
            {content}
        </div>
    )
}
