import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { canTakeFromOtherProject, projectName } from './repositoryChoices'
import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** A repository's name, with the control that adds it to this project or removes it. */
export function RepositoryNameCell({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { installation, busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { includeRepository, removeFromProject } = useActions(reviewHogRepositoriesLogic)

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

    return (
        <div className="flex min-h-8 min-w-0 flex-wrap items-center gap-2">
            <span
                className={`min-w-0 truncate font-mono text-sm font-semibold ${entry.in_project ? '' : 'text-secondary'}`}
                title={name}
            >
                {name}
            </span>
            {canInclude && (
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
            )}
            {!canInclude && canRemove && (
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
        </div>
    )
}
