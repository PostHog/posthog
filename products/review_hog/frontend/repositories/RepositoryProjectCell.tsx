import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { canTakeFromOtherProject, flashForLabel, projectName } from './repositoryChoices'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { RuleControls } from './RuleControls'

/** The project side of one repository: whether this project reviews it, and its exception if any. */
export function RepositoryProjectCell({
    entry,
    className,
}: {
    entry: ReviewRepositoryOverviewEntryApi
    className?: string
}): JSX.Element {
    const { projectSettings, canEdit } = useValues(reviewHogProjectSettingsLogic)
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

    let status: JSX.Element
    if (entry.owner === 'other_project') {
        status = <span className="text-xs text-secondary">Reviewed in {projectName(entry.owner_project)}</span>
    } else if (!entry.in_project) {
        status = <span className="text-xs text-secondary">Not part of this project</span>
    } else if (entry.exception === null) {
        status = (
            <>
                <span className="text-xs text-secondary">
                    Follows project · {flashForLabel(projectSettings?.flash_for ?? 'off')}
                </span>
                {canEdit && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPlus />}
                        tooltip="Add an exception, starting from the project settings"
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
        status = (
            <>
                <LemonTag type="warning" size="small">
                    Exception
                </LemonTag>
                {canEdit && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconX />}
                        tooltip="Clear the exception and follow the project settings again"
                        aria-label={`Clear exception for ${name}`}
                        onClick={() => clearException(entry)}
                        disabledReason={savingReason}
                        data-attr="review-hog-repository-clear-exception"
                    >
                        clear
                    </LemonButton>
                )}
            </>
        )
    }

    return (
        <div className={`flex min-w-0 flex-col gap-1.5 px-4 py-2.5 ${className ?? ''}`}>
            <div className="flex flex-wrap items-center gap-2">
                <span
                    className={`min-w-0 truncate font-mono text-sm font-semibold ${entry.in_project ? '' : 'text-secondary'}`}
                    title={name}
                >
                    {name}
                </span>
                {status}
                {(canInclude || canRemove) && (
                    // Membership sits apart from the exception controls, so adding a repository never reads as clearing one.
                    <span className="ml-auto">
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
                        ) : (
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
                        )}
                    </span>
                )}
            </div>
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
                    dataAttr="review-hog-repository-flash-for"
                />
            )}
        </div>
    )
}
