import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, type LemonSelectOptions, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { MyChoiceValue, myChoiceNote, myChoiceOptions, myChoiceValue, projectName } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { withYouIcons } from './withYouIcons'

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
        const choices = myChoiceOptions(entry)
        // With a choice of your own, going back reads as removing it, the same way an exception is removed.
        const options: LemonSelectOptions<MyChoiceValue> = hasChoice
            ? [
                  { options: [{ value: 'follow', label: 'Remove my choice' }] },
                  { options: withYouIcons(choices.filter((option) => option.value !== 'follow')) },
              ]
            : withYouIcons(choices)
        content = (
            <div className="flex min-w-0 flex-col items-start gap-1">
                <span className="flex max-w-full min-w-0 items-center gap-2">
                    {/* The dot answers "do my PRs here get a review" at a glance, so a column scan finds the off rows. */}
                    <Tooltip
                        title={
                            entry.my_result.flash
                                ? 'Your pull requests here get automatic reviews'
                                : 'Your pull requests here get no automatic review'
                        }
                    >
                        <span
                            className={`inline-block size-2 shrink-0 rounded-full ${entry.my_result.flash ? 'bg-success' : 'bg-border-bold'}`}
                        />
                    </Tooltip>
                    <LemonSelect<MyChoiceValue>
                        size="small"
                        className="min-w-0 shrink"
                        truncateText={{ maxWidthClass: 'max-w-full' }}
                        aria-label={`My choice for ${name}`}
                        value={value}
                        options={options}
                        onChange={(picked) => setMyChoice(entry, picked)}
                        disabledReason={busyReason}
                        data-attr="review-hog-my-choice"
                    />
                </span>
                {note && <span className="pl-4 text-xs text-secondary">{note}</span>}
            </div>
        )
    }

    return (
        <div className={`flex min-w-0 flex-col gap-1 px-4 py-2.5 ${className ?? ''}`}>
            <span className="text-xxs font-semibold uppercase tracking-wide text-secondary @min-[48rem]:hidden">
                My preference
            </span>
            {content}
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
