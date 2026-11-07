import { useActions, useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import { parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { type InboxReviewerOption, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_CLAIMED_BY_YOU, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'
import {
    INBOX_SCOPE_CLAIMED_BY_YOU_LABEL,
    INBOX_SCOPE_ENTIRE_PROJECT_LABEL,
    INBOX_SCOPE_FOR_YOU_LABEL,
} from './inboxToolbarOptions'

/** A person the scope can move to. The signed-in user carries `trailing: '(you)'`. */
export interface InboxScopeMemberOption {
    uuid: string
    name: string
    email: string
    trailing?: string
}

export interface InboxScopeFilterState {
    scope: InboxScope
    /** The teammate the scope names, or null for For you, Claimed by you and Entire project. */
    selectedTeammateUuid: string | null
    isForYou: boolean
    triggerLabel: string
    options: InboxScopeMemberOption[]
    optionsLoading: boolean
    userUuid: string | undefined
    searchReviewers: (query: string) => void
    pick: (next: InboxScope, label?: string) => void
    /** Picking yourself uses the For you scope. */
    pickMember: (uuid: string, label: string) => void
}

function getReviewerOptions(reviewers: InboxReviewerOption[], user: UserType | null): InboxScopeMemberOption[] {
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
 * The reviewer scope picker's state and choices: "Entire project", "Claimed by you", and each teammate,
 * where picking yourself is "For you". Teammates come from the shared `availableReviewers` loader.
 */
export function useInboxScopeFilter(): InboxScopeFilterState {
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
        ? INBOX_SCOPE_FOR_YOU_LABEL
        : scope === INBOX_SCOPE_CLAIMED_BY_YOU
          ? INBOX_SCOPE_CLAIMED_BY_YOU_LABEL
          : selectedTeammateUuid
            ? (selectedTeammateLabel ?? cachedTeammateLabel ?? 'Teammate')
            : INBOX_SCOPE_ENTIRE_PROJECT_LABEL

    const pick = (next: InboxScope, label?: string): void => {
        const nextUuid = parseTeammateInboxScope(next)
        if (label && nextUuid) {
            setKnownTeammate(nextUuid, label)
        }
        setScope(next)
        searchAvailableReviewers('')
    }

    return {
        scope,
        selectedTeammateUuid,
        isForYou,
        triggerLabel,
        options: getReviewerOptions(reviewers, user),
        optionsLoading: availableReviewersLoading,
        userUuid: user?.uuid,
        searchReviewers: searchAvailableReviewers,
        pick,
        pickMember: (uuid, label) => pick(uuid === user?.uuid ? INBOX_SCOPE_FOR_YOU : teammateInboxScope(uuid), label),
    }
}
