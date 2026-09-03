import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { isTeammateInboxScope, parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'
import { InboxPeoplePicker } from './InboxPeoplePicker'

/**
 * Single-dropdown reviewer scope for the flat Reports list: one trigger that names the current
 * scope and opens the shared people picker with "For you" pinned on top, then "Entire project",
 * then each teammate. "For you" is the default scope; a user with no reports suggested to them is
 * auto-switched to "Entire project" (see `shouldDefaultToEntireProject`). The legacy layout keeps
 * the two-segment `InboxScopeSelect` until the redesign flag replaces it. Scope is persisted via
 * `inboxFiltersLogic`; teammates come from its shared `availableReviewers` loader.
 */
export function InboxScopeFilter(): JSX.Element {
    const { scope, availableReviewers: reviewers, availableReviewersLoading } = useValues(inboxFiltersLogic)
    const { setScope, searchAvailableReviewers } = useActions(inboxFiltersLogic)
    const { user } = useValues(userLogic)
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')
    // External reference (callback ref → state so the Popover re-anchors once mounted).
    const [referenceEl, setReferenceEl] = useState<HTMLDivElement | null>(null)
    // Remember the selected teammate's label so the trigger stays correct even while a search
    // query has filtered them out of the server-returned `reviewers` list. Keep the uuid alongside
    // it: a scope change to a different teammate the roster hasn't loaded (search-filtered, or past
    // the 100-row cap) must not fall back to the previous teammate's name.
    const [knownTeammate, setKnownTeammate] = useState<{ uuid: string; label: string } | null>(null)

    const isForYou = scope === INBOX_SCOPE_FOR_YOU
    const selectedTeammateUuid = isTeammateInboxScope(scope) ? parseTeammateInboxScope(scope) : null
    const selectedTeammate = reviewers.find((r) => r.user_uuid === selectedTeammateUuid)
    const selectedTeammateLabel = selectedTeammate ? selectedTeammate.name || selectedTeammate.email : null

    useEffect(() => {
        if (selectedTeammateUuid && selectedTeammateLabel) {
            setKnownTeammate({ uuid: selectedTeammateUuid, label: selectedTeammateLabel })
        }
    }, [selectedTeammateUuid, selectedTeammateLabel])

    // Only reuse the cached label when it names the currently-scoped teammate.
    const cachedTeammateLabel =
        knownTeammate && knownTeammate.uuid === selectedTeammateUuid ? knownTeammate.label : null

    const triggerLabel = isForYou
        ? 'For you'
        : selectedTeammateUuid
          ? (selectedTeammateLabel ?? cachedTeammateLabel ?? 'Teammate')
          : 'Entire project'

    const pick = (next: InboxScope, label?: string): void => {
        const nextUuid = parseTeammateInboxScope(next)
        if (label && nextUuid) {
            setKnownTeammate({ uuid: nextUuid, label })
        }
        setScope(next)
        setOpen(false)
        setSearch('')
        searchAvailableReviewers('')
    }

    return (
        <>
            <div ref={setReferenceEl} className="inline-flex">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setOpen((v) => !v)}
                    sideIcon={<IconChevronDown className="text-tertiary" />}
                    tooltip="See the reports suggested to you, every report in the project, or a teammate's"
                    // Name the active scope for assistive tech. Without this, LemonButton copies the
                    // string tooltip into aria-label, so a screen reader hears the help text and never
                    // the current scope.
                    aria-label={`Report scope: ${triggerLabel}`}
                    data-attr="inbox-scope-filter"
                >
                    <span className="max-w-[160px] truncate">{triggerLabel}</span>
                </LemonButton>
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
                // The pinned "For you" row already stands for the signed-in user, so their own
                // roster row would be a second control writing a different scope for the same view.
                people={reviewers
                    .filter((reviewer) => reviewer.user_uuid !== user?.uuid)
                    .map((reviewer) => ({
                        uuid: reviewer.user_uuid,
                        name: reviewer.name,
                        email: reviewer.email,
                    }))}
                loading={availableReviewersLoading}
                selectedUuid={scope === INBOX_SCOPE_ENTIRE_PROJECT ? null : (selectedTeammateUuid ?? undefined)}
                forYou={{ active: isForYou, onPick: () => pick(INBOX_SCOPE_FOR_YOU) }}
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
