import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { FLASH_FOR_OPTIONS, canTakeFromOtherProject, projectName } from './repositoryChoices'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { RuleControls } from './RuleControls'
import { RuleStateIcon } from './RuleStateIcon'

/** The project side of one repository: whether this project reviews it, and its exception if any. */
export function RepositoryProjectCell({
    entry,
    className,
}: {
    entry: ReviewRepositoryOverviewEntryApi
    className?: string
}): JSX.Element {
    const { canEdit, projectSettings } = useValues(reviewHogProjectSettingsLogic)
    const { installation, busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const {
        includeRepository,
        removeFromProject,
        addException,
        clearException,
        setExceptionFlashFor,
        addExceptionPerson,
        removeExceptionPerson,
    } = useActions(reviewHogRepositoriesLogic)

    const name = entry.full_name
    const savingReason = busyRepositories.includes(name) ? 'Saving…' : undefined
    const takeable = canTakeFromOtherProject(entry, installation)
    const canInclude = canEdit && (entry.owner === 'none' || takeable)
    const canRemove = canEdit && entry.in_project && entry.selected && installation?.scope !== 'all'

    const include = (): void => {
        if (!takeable) {
            includeRepository(entry)
            return
        }
        LemonDialog.open({
            title: `Include ${name} in this project?`,
            description: `This takes ${name} from ${projectName(entry.owner_project)}, which reviews all repositories of ${installation?.account_name ?? 'this GitHub account'}. Both projects get an activity log entry.`,
            primaryButton: {
                children: 'Include in project',
                onClick: () => includeRepository(entry),
                'data-attr': 'review-hog-repository-take-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const projectFlashFor = projectSettings?.flash_for ?? 'off'
    let status: JSX.Element | null
    if (entry.owner === 'other_project') {
        status = <span className="text-xs text-secondary">Reviewed in {projectName(entry.owner_project)}</span>
    } else if (!entry.in_project) {
        status = <span className="text-xs text-secondary">Not part of this project</span>
    } else if (entry.exception === null) {
        // A row on the project rule carries no text, only the project icon: the project default above says the rest once.
        const projectRule = FLASH_FOR_OPTIONS.find((option) => option.value === projectFlashFor)?.label
        const addExceptionButton = canEdit ? (
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconPlus />}
                tooltip="Add an exception, starting from the project default"
                aria-label={`Add exception for ${name}`}
                onClick={() => addException(entry)}
                disabledReason={savingReason}
                data-attr="review-hog-repository-add-exception"
            >
                Exception
            </LemonButton>
        ) : null
        status = (
            <>
                <Tooltip title={`Follows the project default: ${projectRule?.toLowerCase()}`}>
                    <span className="flex">
                        <RuleStateIcon flashFor={projectFlashFor} />
                    </span>
                </Tooltip>
                {addExceptionButton}
            </>
        )
    } else {
        // The "Exception" tag sits on the line of the exception's own select, in RuleControls.
        status = null
    }

    return (
        <div className={`flex min-w-0 flex-col gap-1.5 px-4 py-2.5 ${className ?? ''}`}>
            {(status || canInclude || canRemove) && (
                <div className="flex min-h-7 flex-wrap items-center gap-2">
                    {status}
                    {(canInclude || canRemove) && (
                        <span className="ml-auto flex items-center gap-1">
                            {canInclude ? (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    aria-label={`Include ${name} in this project`}
                                    onClick={include}
                                    disabledReason={savingReason}
                                    data-attr="review-hog-repository-include"
                                >
                                    Include in project
                                </LemonButton>
                            ) : canRemove ? (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    aria-label={`Remove ${name} from this project`}
                                    onClick={() => removeFromProject(entry)}
                                    disabledReason={savingReason}
                                    data-attr="review-hog-repository-remove"
                                >
                                    Remove from project
                                </LemonButton>
                            ) : null}
                        </span>
                    )}
                </div>
            )}
            {entry.in_project && entry.exception !== null && (
                <RuleControls
                    label={`Exception for ${name}`}
                    flashFor={entry.exception.flash_for}
                    people={entry.exception.people}
                    canEdit={canEdit}
                    disabledReason={canEdit ? savingReason : 'Only project admins can change this'}
                    onChangeFlashFor={(flashFor) => setExceptionFlashFor(entry, flashFor)}
                    onAddPerson={(userId, kind) => addExceptionPerson(entry, userId, kind)}
                    onRemovePerson={(person) => removeExceptionPerson(entry, person)}
                    tag={
                        <LemonTag type="warning" size="small">
                            Exception
                        </LemonTag>
                    }
                    removeException={canEdit ? { projectFlashFor, onRemove: () => clearException(entry) } : undefined}
                    dataAttr="review-hog-repository-flash-for"
                />
            )}
        </div>
    )
}
