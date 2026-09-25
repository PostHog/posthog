import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect, type MemberSelectProps } from 'lib/components/MemberSelect'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import { parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { type InboxReviewerOption, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'

function getReviewerOptions(
    reviewers: InboxReviewerOption[],
    user: UserType | null
): NonNullable<MemberSelectProps['options']> {
    const options = reviewers.map((reviewer) => ({
        uuid: reviewer.user_uuid,
        name: reviewer.name,
        email: reviewer.email,
        trailing: reviewer.user_uuid === user?.uuid ? '(you)' : undefined,
    }))
    if (!user || options.some((option) => option.uuid === user.uuid)) {
        return options
    }
    return [
        {
            uuid: user.uuid,
            name: `${user.first_name} ${user.last_name ?? ''}`.trim() || user.email,
            email: user.email,
            trailing: '(you)',
        },
        ...options,
    ]
}

/**
 * Single-dropdown reviewer scope for the flat Reports list: one trigger that names the current
 * scope and opens the shared people picker with "Entire project" and each teammate. Selecting
 * yourself uses the "For you" scope. A user with no reports suggested to them is
 * auto-switched to "Entire project" (see `shouldDefaultToEntireProject`). The legacy layout keeps
 * the two-segment `InboxScopeSelect` until the redesign flag replaces it. Scope is persisted via
 * `inboxFiltersLogic`; teammates come from its shared `availableReviewers` loader.
 */
export function InboxScopeFilter(): JSX.Element {
    const {
        scope,
        availableReviewers: reviewers,
        availableReviewersLoading,
        knownTeammate,
    } = useValues(inboxFiltersLogic)
    const { setScope, searchAvailableReviewers, setKnownTeammate } = useActions(inboxFiltersLogic)
    const { user } = useValues(userLogic)

    const isForYou = scope === INBOX_SCOPE_FOR_YOU
    const selectedTeammateUuid = parseTeammateInboxScope(scope)
    const selectedTeammate = reviewers.find((r) => r.user_uuid === selectedTeammateUuid)
    const selectedTeammateLabel = selectedTeammate ? selectedTeammate.name || selectedTeammate.email : null

    // Only reuse the cached label when it names the currently-scoped teammate.
    const cachedTeammateLabel =
        knownTeammate && knownTeammate.uuid === selectedTeammateUuid ? knownTeammate.label : null

    const triggerLabel = isForYou
        ? 'For you'
        : selectedTeammateUuid
          ? (selectedTeammateLabel ?? cachedTeammateLabel ?? 'Teammate')
          : 'Entire project'

    const options = getReviewerOptions(reviewers, user)

    const pick = (next: InboxScope, label?: string): void => {
        const nextUuid = parseTeammateInboxScope(next)
        if (label && nextUuid) {
            setKnownTeammate(nextUuid, label)
        }
        setScope(next)
        searchAvailableReviewers('')
    }

    return (
        <MemberSelect
            value={selectedTeammateUuid}
            defaultLabel="Entire project"
            options={options}
            optionsLoading={availableReviewersLoading}
            onSearch={searchAvailableReviewers}
            onChange={() => pick(INBOX_SCOPE_ENTIRE_PROJECT)}
            onSelectOption={(uuid, label) =>
                pick(uuid === user?.uuid ? INBOX_SCOPE_FOR_YOU : teammateInboxScope(uuid), label)
            }
        >
            {() => (
                <LemonButton
                    size="small"
                    type="secondary"
                    tooltip="See the reports suggested to you, every report in the project, or a teammate's"
                    // Name the active scope for assistive tech. Without this, LemonButton copies the
                    // string tooltip into aria-label, so a screen reader hears the help text and never
                    // the current scope.
                    aria-label={`Report scope: ${triggerLabel}`}
                    data-attr="inbox-scope-filter"
                >
                    <span className="max-w-[160px] truncate">{triggerLabel}</span>
                </LemonButton>
            )}
        </MemberSelect>
    )
}
