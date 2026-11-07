import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonInput, Spinner } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { InboxReportActionSurface } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { AvailableReviewerOption, getReviewerOptionDisplayName } from './reviewerDisplay'
import { toggleSuggestedReviewer } from './suggestedReviewers'

/**
 * Searchable org-member list that toggles a report's suggested reviewers, with optimistic updates.
 * Rendered by the detail pane's "Add" popover and by the report context menu's Reviewers submenu,
 * so both surfaces offer the same picker. Mounting it mounts the report detail logic, which loads
 * the reviewer artefact and the searchable members.
 */
export function ReviewerSearchList({
    report,
    surface,
}: {
    report: SignalReport
    /** Which surface hosts the list, for the add/remove reviewer analytics. */
    surface: InboxReportActionSurface
}): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { displayReviewers, addReviewerOptions, availableReviewersLoading, isUpdatingReviewers, reportArtefacts } =
        useValues(logic)
    const { updateReviewers, searchAvailableReviewers } = useActions(logic)
    const reviewersLoaded = reportArtefacts !== null
    const [query, setQuery] = useState('')

    const baseReviewers = displayReviewers ?? []
    // Assigned set keyed by user uuid (how `reviewerMatchesOption` matches), so the membership
    // check is O(1) per option instead of scanning every reviewer per keystroke.
    const assignedUuids = useMemo(
        () => new Set(baseReviewers.map((r) => r.user?.uuid).filter(Boolean)),
        [baseReviewers]
    )
    const meUuid = addReviewerOptions[0]?.user_uuid

    const toggleOption = (option: AvailableReviewerOption): void =>
        toggleSuggestedReviewer({ report, surface, option, reviewers: baseReviewers, updateReviewers })

    return (
        <div
            className="flex w-72 flex-col gap-2 p-1"
            // Inside a Radix submenu, keystrokes are typeahead over the menu items and some keys
            // close the submenu. Keep everything except Escape in the search input; Escape still
            // reaches the menu so it can close.
            onKeyDown={(event) => {
                if (event.key !== 'Escape') {
                    event.stopPropagation()
                }
            }}
        >
            <LemonInput
                type="search"
                size="small"
                // Search inputs default to a 240px cap, which reads as a broken layout in a panel
                // only slightly wider; span the panel instead.
                fullWidth
                autoFocus
                placeholder="Search users…"
                value={query}
                onChange={(value) => {
                    setQuery(value)
                    searchAvailableReviewers(value)
                }}
            />
            <div className="flex max-h-72 flex-col overflow-y-auto">
                {availableReviewersLoading || !reviewersLoaded ? (
                    <span className="flex items-center gap-2 px-1 py-2 text-xs text-tertiary">
                        <Spinner className="size-3" />
                        Searching…
                    </span>
                ) : addReviewerOptions.length === 0 ? (
                    <span className="px-1 py-2 text-xs text-tertiary">No users found.</span>
                ) : (
                    addReviewerOptions.map((option) => {
                        const assigned = assignedUuids.has(option.user_uuid)
                        const isMe = meUuid === option.user_uuid
                        return (
                            <button
                                key={option.user_uuid}
                                type="button"
                                // The row toggles a reviewer both ways and shows state only through a
                                // decorative check, so announce it: a screen reader needs the pressed
                                // state to tell adding from removing before activation.
                                aria-pressed={assigned}
                                disabled={isUpdatingReviewers}
                                className="flex w-full items-start justify-between gap-2 rounded px-1.5 py-1 text-left transition-colors hover:bg-fill-highlight-50 disabled:opacity-60"
                                onClick={() => toggleOption(option)}
                            >
                                <div className="flex min-w-0 items-center gap-2">
                                    <PersonDisplay
                                        person={{
                                            properties: {
                                                email: option.email,
                                                name: option.name,
                                            },
                                        }}
                                        displayName={getReviewerOptionDisplayName(option, isMe)}
                                        withIcon="xs"
                                        noLink
                                        noPopover
                                    />
                                </div>
                                <span className="flex size-4 shrink-0 items-center justify-center text-primary">
                                    {assigned && <IconCheck className="text-sm" />}
                                </span>
                            </button>
                        )
                    })
                )}
            </div>
        </div>
    )
}
