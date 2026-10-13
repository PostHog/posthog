import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { MyChoiceValue, myChoiceNote, myChoiceOptions, myChoiceValue, projectName } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** The viewer's side of one repository: what their own pull requests get there, and their choice. */
export function RepositoryMyCell({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setMyChoice } = useActions(reviewHogRepositoriesLogic)
    const name = entry.full_name
    const hasChoice = entry.my_choice !== null
    const busyReason = busyRepositories.includes(name) ? 'Saving…' : undefined
    const otherProjectId = entry.owner === 'other_project' ? entry.owner_project?.id : null

    let content: JSX.Element
    if (entry.owner === 'other_project') {
        content = (
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
        content = <span className="text-xs text-secondary">No automatic review</span>
    } else {
        content = (
            <LemonSelect<MyChoiceValue>
                size="small"
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
    const note = entry.in_project && entry.owner !== 'other_project' ? myChoiceNote(entry) : null

    return (
        <div className="flex min-w-0 flex-col items-start gap-1">
            <div className="flex min-h-8 max-w-full min-w-0 flex-wrap items-center gap-2">
                <span className="text-xs text-secondary @min-[48rem]:hidden">Mine:</span>
                {content}
            </div>
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
    )
}
