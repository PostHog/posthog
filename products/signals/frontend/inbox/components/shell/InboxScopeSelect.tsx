import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconAsterisk, IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'

import { isTeammateInboxScope, parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'

/**
 * Two-segment scope toggle built on `LemonSegmentedButton`. Left segment is
 * "For you"; the right segment shows "Entire project" or the selected teammate's
 * name and opens a searchable people picker ("Entire project" + each teammate,
 * with avatars). One-to-one port of desktop `InboxScopeSelect` (segmented control
 * + combobox), in LemonUI. Scope is persisted via `inboxFiltersLogic`; teammates
 * come from its shared `availableReviewers` loader.
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
            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                referenceElement={referenceEl}
                placement="bottom-end"
                overlay={
                    <div className="w-[240px] p-1">
                        <LemonInput
                            type="search"
                            size="small"
                            placeholder="Search people…"
                            value={search}
                            onChange={(value) => {
                                setSearch(value)
                                searchAvailableReviewers(value)
                            }}
                            autoFocus
                            className="mb-1"
                        />
                        <div className="max-h-[16rem] overflow-y-auto space-y-px">
                            <ScopeRow
                                active={scope === INBOX_SCOPE_ENTIRE_PROJECT}
                                onClick={() => pick(INBOX_SCOPE_ENTIRE_PROJECT)}
                                avatar={
                                    <span
                                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-dashed border-secondary text-tertiary"
                                        aria-hidden
                                    >
                                        <IconAsterisk className="text-xs" />
                                    </span>
                                }
                                label="Entire project"
                            />
                            {reviewers.map((reviewer) => (
                                <ScopeRow
                                    key={reviewer.user_uuid}
                                    active={selectedTeammateUuid === reviewer.user_uuid}
                                    onClick={() =>
                                        pick(teammateInboxScope(reviewer.user_uuid), reviewer.name || reviewer.email)
                                    }
                                    avatar={
                                        <ProfilePicture
                                            user={{ first_name: reviewer.name, email: reviewer.email }}
                                            size="sm"
                                        />
                                    }
                                    label={reviewer.name || reviewer.email}
                                />
                            ))}
                            {availableReviewersLoading ? (
                                <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-tertiary">
                                    <Spinner className="size-3" />
                                    Searching…
                                </div>
                            ) : reviewers.length === 0 ? (
                                <div className="px-2 py-1.5 text-xs text-tertiary">No matching people.</div>
                            ) : null}
                        </div>
                    </div>
                }
            />
        </>
    )
}

function ScopeRow({
    active,
    onClick,
    avatar,
    label,
}: {
    active: boolean
    onClick: () => void
    avatar: JSX.Element
    label: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors',
                active ? 'bg-surface-secondary font-medium' : 'hover:bg-surface-secondary'
            )}
        >
            {avatar}
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {active && <IconCheck className="shrink-0 text-sm text-default" />}
        </button>
    )
}
