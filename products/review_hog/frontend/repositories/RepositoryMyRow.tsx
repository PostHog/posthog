import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { MyChoiceValue, myChoiceNote, myChoiceOptions, myChoiceValue, projectName } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** The viewer's side of one repository: what their own pull requests get there, and their choice. */
export function RepositoryMyRow({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setMyChoice } = useActions(reviewHogRepositoriesLogic)
    const name = entry.full_name
    const hasChoice = entry.my_choice !== null
    const busyReason = busyRepositories.includes(name) ? 'Saving…' : undefined

    let note: string | null = null
    let choice: JSX.Element
    if (entry.owner === 'other_project') {
        const otherProjectId = entry.owner_project?.id
        choice = (
            <span className="text-xs">
                {otherProjectId ? (
                    <Link to={urls.project(otherProjectId, urls.codeReview())} disableClientSideRouting>
                        Open {projectName(entry.owner_project)}
                    </Link>
                ) : (
                    <span className="text-secondary">Reviewed in {projectName(entry.owner_project)}</span>
                )}
                <span className="text-secondary">. Its rules decide your reviews here.</span>
            </span>
        )
    } else if (!entry.in_project) {
        choice = <span className="text-xs text-secondary">Not part of this project</span>
    } else {
        note = myChoiceNote(entry)
        choice = (
            <LemonSelect<MyChoiceValue>
                size="small"
                // A bordered select marks a choice the viewer made. An inherited value stays plain.
                type={hasChoice ? 'secondary' : 'tertiary'}
                className="max-w-full"
                truncateText={{ maxWidthClass: 'max-w-full' }}
                aria-label={`My choice for ${name}`}
                value={myChoiceValue(entry)}
                options={myChoiceOptions(entry)}
                onChange={(picked) => setMyChoice(entry, picked)}
                disabledReason={busyReason}
                data-attr="review-hog-my-choice"
            />
        )
    }

    return (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2.5">
            <div className="flex min-w-48 flex-1 flex-col gap-0.5">
                <span
                    className={`min-w-0 truncate font-mono text-sm font-semibold ${entry.in_project ? '' : 'text-secondary'}`}
                    title={name}
                >
                    {name}
                </span>
                {note && <span className="text-xs text-secondary">{note}</span>}
                {hasChoice && !entry.in_project && (
                    <div className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                        Your saved choice applies if this repository joins this project.
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setMyChoice(entry, 'follow')}
                            disabledReason={busyReason}
                            data-attr="review-hog-clear-my-choice"
                        >
                            Clear my choice
                        </LemonButton>
                    </div>
                )}
            </div>
            <div className="flex min-h-8 max-w-full min-w-0 items-center">{choice}</div>
        </div>
    )
}
