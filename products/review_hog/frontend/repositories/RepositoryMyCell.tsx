import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { MyChoiceValue, myChoiceNote, myChoiceOptions, myChoiceValue, projectName } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { YouMark } from './YouMark'

/** The viewer's side of one repository: what their own pull requests get there, and their choice. */
export function RepositoryMyCell({
    entry,
    className,
}: {
    entry: ReviewRepositoryOverviewEntryApi
    className?: string
}): JSX.Element {
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setMyChoice } = useActions(reviewHogRepositoriesLogic)
    const name = entry.full_name
    const value = myChoiceValue(entry)
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
                <span className="text-secondary"> · its rules decide your reviews here</span>
            </span>
        )
    } else if (!entry.in_project) {
        content = <span className="text-xs text-secondary">No automatic review. Not part of this project.</span>
    } else {
        const note = myChoiceNote(entry)
        content = (
            <div className="flex min-w-0 flex-col items-start gap-1">
                <LemonSelect<MyChoiceValue>
                    size="small"
                    aria-label={`My choice for ${name}`}
                    value={value}
                    options={myChoiceOptions(entry)}
                    onChange={(picked) => setMyChoice(entry, picked)}
                    disabledReason={busyReason}
                    data-attr="review-hog-my-choice"
                />
                {note && <span className="text-xs text-secondary">{note}</span>}
            </div>
        )
    }

    return (
        <div className={`flex min-w-0 flex-col justify-center gap-1 px-4 py-2.5 ${className ?? ''}`}>
            <span className="text-xxs font-semibold uppercase tracking-wide text-secondary @min-[48rem]:hidden">
                My choice
            </span>
            <div className="flex items-start gap-1">
                {/* Lines the mark up with the select, not with the note under it. */}
                <span className="pt-1.5">
                    <YouMark shown={hasChoice} />
                </span>
                {content}
            </div>
            {hasChoice && !entry.in_project && (
                <div className="flex flex-wrap items-center gap-1 pl-10 text-xs text-secondary">
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
