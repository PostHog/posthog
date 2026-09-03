import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonInput, Spinner } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'
import {
    AvailableReviewerOption,
    getReviewerOptionDisplayName,
    reviewerMatchesOption,
    reviewersToWriteContent,
} from './reviewerDisplay'

/**
 * Remove one suggested reviewer, optimistically, and record the removal. One implementation for
 * the picker's untoggle and the detail section's per-row remove button, so the write payload and
 * the analytics cannot diverge.
 */
export function removeSuggestedReviewer({
    report,
    surface,
    target,
    reviewers,
    updateReviewers,
}: {
    report: SignalReport
    surface: InboxReportActionSurface
    target: EnrichedReviewer
    reviewers: EnrichedReviewer[]
    updateReviewers: (content: Record<string, string>[], optimistic: EnrichedReviewer[]) => void
}): void {
    captureInboxReportAction({
        report,
        actionType: 'remove_suggested_reviewer',
        surface,
        // Match the shared cross-client contract: the real GitHub login when known, plus the user
        // uuid desktop always sends, so a breakdown by either property lines web up with desktop.
        extra: {
            suggested_reviewer_login: target.github_login || undefined,
            suggested_reviewer_uuid: target.user?.uuid,
        },
    })
    const next = reviewers.filter((r) => r !== target)
    updateReviewers(reviewersToWriteContent(next), next)
}

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
    // A write is a full replacement, and `displayReviewers` is null until the artefact log lands. The
    // context menu mounts this logic fresh, so the member search can resolve before the artefacts; a
    // click in that window would build the write from an empty base and silently wipe every existing
    // reviewer. Wait for the artefacts (as the detail pane's `SuggestedReviewersSection` already does)
    // before the rows become clickable. `reportArtefacts !== null` with no reviewer artefact is a real
    // empty list, so this doesn't block adding the first reviewer.
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

    const toggleOption = (option: AvailableReviewerOption): void => {
        const existing = baseReviewers.find((r) => reviewerMatchesOption(r, option))
        if (existing) {
            removeSuggestedReviewer({ report, surface, target: existing, reviewers: baseReviewers, updateReviewers })
            return
        }
        const optimisticEntry: EnrichedReviewer = {
            github_login: '',
            github_name: option.name || null,
            relevant_commits: [],
            user: {
                id: 0,
                uuid: option.user_uuid,
                email: option.email,
                first_name: option.name,
                last_name: '',
            },
        }
        const next = [...baseReviewers, optimisticEntry]
        captureInboxReportAction({
            report,
            actionType: 'add_suggested_reviewer',
            surface,
            // The web option carries only the PostHog user uuid, never a GitHub login, so record it
            // under suggested_reviewer_uuid to match the shared cross-client event contract.
            extra: { suggested_reviewer_uuid: option.user_uuid },
        })
        updateReviewers([...reviewersToWriteContent(baseReviewers), { user_uuid: option.user_uuid }], next)
    }

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
