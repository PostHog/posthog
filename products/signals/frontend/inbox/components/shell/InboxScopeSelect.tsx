import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { isTeammateInboxScope, parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'
import { InboxPeoplePicker } from './InboxPeoplePicker'

/**
 * Two-segment scope toggle built on `LemonSegmentedButton`. Left segment is
 * "For you"; the right segment shows "Entire project" or the selected teammate's
 * name and opens the shared people picker ("Entire project" + each teammate).
 * One-to-one port of desktop `InboxScopeSelect` (segmented control + combobox),
 * in LemonUI. Scope is persisted via `inboxFiltersLogic`; teammates come from
 * its shared `availableReviewers` loader.
 */
export function InboxScopeSelect(): JSX.Element {
    const { scope, availableReviewers: reviewers, availableReviewersLoading } = useValues(inboxFiltersLogic)
    const { setScope, searchAvailableReviewers } = useActions(inboxFiltersLogic)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    // External reference (callback ref → state so the Popover re-anchors once mounted).
    // Anchoring via `referenceElement` keeps the segment buttons OUT of the popover-reference
    // context, so LemonButton doesn't auto-add its own dropdown chevron to each segment.
    const [referenceEl, setReferenceEl] = useState<HTMLDivElement | null>(null)
    // Remember the selected teammate's label so the trigger stays correct even while a search
    // query has filtered them out of the server-returned `reviewers` list.
    const [knownTeammateLabel, setKnownTeammateLabel] = useState<string | null>(null)

    const isForYou = scope === INBOX_SCOPE_FOR_YOU
    const selectedTeammateUuid = isTeammateInboxScope(scope) ? parseTeammateInboxScope(scope) : null
    const selectedTeammate = reviewers.find((r) => r.user_uuid === selectedTeammateUuid)
    const selectedTeammateLabel = selectedTeammate ? selectedTeammate.name || selectedTeammate.email : null

    useEffect(() => {
        if (selectedTeammateUuid && selectedTeammateLabel) {
            setKnownTeammateLabel(selectedTeammateLabel)
        }
    }, [selectedTeammateUuid, selectedTeammateLabel])

    const rightLabel = selectedTeammateUuid
        ? (selectedTeammateLabel ?? knownTeammateLabel ?? 'Teammate')
        : 'Entire project'

    const pick = (next: InboxScope, label?: string): void => {
        if (label) {
            setKnownTeammateLabel(label)
        }
        setScope(next)
        setOpen(false)
        setSearch('')
        searchAvailableReviewers('')
    }

    return (
        <>
            <div ref={setReferenceEl} className="inline-flex">
                <LemonSegmentedButton
                    size="small"
                    value={isForYou ? 'for-you' : 'other'}
                    onChange={(value) => {
                        if (value === 'for-you') {
                            // Left segment selects the For-you scope and closes the picker.
                            setScope(INBOX_SCOPE_FOR_YOU)
                            setOpen(false)
                        } else {
                            // Right segment opens the people picker; the scope only changes
                            // once a row (Entire project / teammate) is picked.
                            setOpen((v) => !v)
                        }
                    }}
                    options={[
                        {
                            value: 'for-you',
                            label: 'For you',
                            tooltip: 'Only reports where agents suggested you as a reviewer',
                        },
                        {
                            value: 'other',
                            label: (
                                <span className="inline-flex items-center gap-1">
                                    <span className="max-w-[160px] truncate">{rightLabel}</span>
                                    <IconChevronDown className="text-tertiary" />
                                </span>
                            ),
                            tooltip: "See every report in the project, or a specific teammate's",
                        },
                    ]}
                />
            </div>
            <InboxPeoplePicker
                visible={open}
                referenceElement={referenceEl}
                onClose={() => setOpen(false)}
                search={search}
                onSearch={(value) => {
                    setSearch(value)
                    searchAvailableReviewers(value)
                }}
                people={reviewers.map((reviewer) => ({
                    uuid: reviewer.user_uuid,
                    name: reviewer.name,
                    email: reviewer.email,
                }))}
                loading={availableReviewersLoading}
                selectedUuid={scope === INBOX_SCOPE_ENTIRE_PROJECT ? null : (selectedTeammateUuid ?? undefined)}
                everyoneLabel="Entire project"
                onPick={(person) =>
                    person
                        ? pick(teammateInboxScope(person.uuid), person.name || person.email)
                        : pick(INBOX_SCOPE_ENTIRE_PROJECT)
                }
            />
        </>
    )
}
