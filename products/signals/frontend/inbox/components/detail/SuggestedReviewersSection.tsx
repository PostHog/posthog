import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconPeople, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'

const MAX_VISIBLE_REVIEWERS = 5
import { DetailSection } from './DetailSection'
import { removeSuggestedReviewer, ReviewerSearchList } from './ReviewerSearchList'

/**
 * Suggested reviewers for the report, read from the `suggested_reviewers` artefact, with add/remove
 * editing. Mirrors desktop's `SuggestedReviewersSection`: a search popover to add org members (current
 * user pinned "Me"), per-row remove, and an optimistic update that converges on the reloaded artefact.
 */
export function SuggestedReviewersSection({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { displayReviewers, isUpdatingReviewers, reportArtefacts } = useValues(logic)
    const { updateReviewers } = useActions(logic)

    const [addOpen, setAddOpen] = useState(false)
    const [showAllReviewers, setShowAllReviewers] = useState(false)

    const baseReviewers = displayReviewers ?? []

    // Wait for the artefact log to load before rendering, so we don't flash an empty state that then
    // fills in. Once loaded, always render — a report with zero reviewers still shows the "Add" affordance
    // so a reviewer can be assigned from scratch.
    if (reportArtefacts === null) {
        return null
    }

    const removeReviewer = (target: EnrichedReviewer): void =>
        removeSuggestedReviewer({ report, surface: 'detail_pane', target, reviewers: baseReviewers, updateReviewers })

    return (
        <DetailSection
            icon={<IconPeople />}
            title="Reviewers"
            collapsible
            afterTitle={
                <Tooltip title="Suggested reviewers are tracked in PostHog. To request a review on GitHub, add them on the pull request directly.">
                    <span className="-m-1 flex cursor-help items-center p-1 text-base text-tertiary">
                        <IconInfo />
                    </span>
                </Tooltip>
            }
            rightSlot={
                <div className="flex items-center gap-2">
                    {isUpdatingReviewers && <Spinner className="size-3" />}
                    <LemonDropdown
                        visible={addOpen}
                        onClickOutside={() => setAddOpen(false)}
                        closeOnClickInside={false}
                        placement="bottom-end"
                        overlay={<ReviewerSearchList report={report} surface="detail_pane" />}
                    >
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconPlus />}
                            onClick={() => setAddOpen((open) => !open)}
                        >
                            Add
                        </LemonButton>
                    </LemonDropdown>
                </div>
            }
        >
            {baseReviewers.length === 0 ? (
                <span className="text-xs text-tertiary">No reviewers assigned. Use "Add" to suggest one.</span>
            ) : (
                <div className="@container flex flex-col gap-1.5">
                    {(showAllReviewers ? baseReviewers : baseReviewers.slice(0, MAX_VISIBLE_REVIEWERS)).map(
                        (reviewer: EnrichedReviewer) => (
                            <ReviewerRow
                                key={reviewer.user?.uuid ?? reviewer.github_login}
                                reviewer={reviewer}
                                disabled={isUpdatingReviewers}
                                onRemove={() => removeReviewer(reviewer)}
                            />
                        )
                    )}
                    {baseReviewers.length > MAX_VISIBLE_REVIEWERS && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            fullWidth
                            onClick={() => setShowAllReviewers((show) => !show)}
                            className="text-tertiary"
                        >
                            {showAllReviewers ? 'Show less' : `Show all (${baseReviewers.length})`}
                        </LemonButton>
                    )}
                </div>
            )}
        </DetailSection>
    )
}

function ReviewerRow({
    reviewer,
    disabled,
    onRemove,
}: {
    reviewer: EnrichedReviewer
    disabled: boolean
    onRemove: () => void
}): JSX.Element {
    const displayName = reviewer.github_name ?? reviewer.user?.first_name ?? reviewer.github_login
    const reason = reviewer.reason ?? reviewer.relevant_commits[0]?.reason ?? null
    const githubUrl = reviewer.github_login ? `https://github.com/${reviewer.github_login}` : null

    const person = (
        <PersonDisplay
            person={{
                properties: {
                    email: reviewer.user?.email,
                    name: displayName,
                },
            }}
            displayName={displayName}
            withIcon="xs"
            noLink
            noPopover
        />
    )

    return (
        <div className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded px-1.5 py-1.5 @lg:grid-cols-[minmax(8rem,10rem)_minmax(0,1fr)_auto]">
            {/* no row hover: the row isn't clickable, only the remove button is */}
            <Tooltip
                title={
                    reviewer.user
                        ? githubUrl
                            ? `@${reviewer.github_login} on GitHub`
                            : undefined
                        : `${displayName} hasn't connected their GitHub account to PostHog. Ask them to do so in Settings!`
                }
            >
                <span className={!reviewer.user ? 'min-w-0 opacity-75' : 'min-w-0'}>
                    {/* The GitHub handle's link is merged into the name: clicking it opens the
                        reviewer's GitHub profile, flagged by the external-link icon. */}
                    {githubUrl ? (
                        <Link
                            to={githubUrl}
                            target="_blank"
                            className="inline-flex items-center gap-1 text-default hover:text-primary"
                        >
                            {person}
                        </Link>
                    ) : (
                        person
                    )}
                </span>
            </Tooltip>
            <div className="col-span-2 row-start-2 flex min-w-0 flex-col gap-0.5 [overflow-wrap:anywhere] @lg:col-span-1 @lg:row-start-auto">
                {reviewer.relevant_commits.length > 0 && (
                    <span className="text-xs text-tertiary">
                        {reviewer.relevant_commits.map((commit, i) => (
                            <span key={commit.sha}>
                                {i > 0 && ', '}
                                <Link
                                    to={commit.url}
                                    target="_blank"
                                    className="font-mono text-tertiary hover:text-primary"
                                >
                                    {commit.sha.slice(0, 7)}
                                </Link>
                            </span>
                        ))}
                    </span>
                )}
                {reason && <span className="text-xs text-tertiary leading-snug">{reason}</span>}
            </div>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconX />}
                disabledReason={disabled ? 'Updating…' : undefined}
                onClick={onRemove}
                tooltip={`Remove ${reviewer.github_login || reviewer.user?.first_name || 'reviewer'}`}
                // Hover reveal keeps rows quiet with a mouse, but a coarse pointer (phone, tablet) has no
                // hover state, so the button stays visible there and whenever the row holds keyboard focus.
                className="opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100"
            />
        </div>
    )
}
