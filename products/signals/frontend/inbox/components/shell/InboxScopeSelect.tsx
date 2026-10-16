import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { parseTeammateInboxScope, teammateInboxScope } from '../../inboxMembership'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, InboxScope } from '../../types'

export function InboxScopeSelect(): JSX.Element {
    const {
        scope,
        availableReviewers: reviewers,
        availableReviewersLoading,
        knownTeammate,
    } = useValues(inboxFiltersLogic)
    const { setScope, searchAvailableReviewers, setKnownTeammate } = useActions(inboxFiltersLogic)

    const selectedUuid = parseTeammateInboxScope(scope)
    const selectedTeammate = reviewers.find((reviewer) => reviewer.user_uuid === selectedUuid)
    const selectedLabel = selectedTeammate ? selectedTeammate.name || selectedTeammate.email : null

    const rightLabel = selectedUuid
        ? (selectedLabel ?? (knownTeammate?.uuid === selectedUuid ? knownTeammate.label : null) ?? 'Teammate')
        : 'Entire project'

    const pick = (next: InboxScope, label?: string): void => {
        const nextUuid = parseTeammateInboxScope(next)
        if (nextUuid && label) {
            setKnownTeammate(nextUuid, label)
        }
        setScope(next)
        searchAvailableReviewers('')
    }

    return (
        <div className="inline-flex">
            <LemonButton
                size="small"
                type="secondary"
                active={scope === INBOX_SCOPE_FOR_YOU}
                onClick={() => pick(INBOX_SCOPE_FOR_YOU)}
                tooltip="Only reports where agents suggested you as a reviewer"
            >
                For you
            </LemonButton>
            <MemberSelect
                value={selectedUuid}
                defaultLabel="Entire project"
                options={reviewers.map((reviewer) => ({
                    uuid: reviewer.user_uuid,
                    name: reviewer.name,
                    email: reviewer.email,
                }))}
                optionsLoading={availableReviewersLoading}
                onSearch={searchAvailableReviewers}
                onChange={() => pick(INBOX_SCOPE_ENTIRE_PROJECT)}
                onSelectOption={(uuid, label) => pick(teammateInboxScope(uuid), label)}
            >
                {() => (
                    <LemonButton
                        size="small"
                        type="secondary"
                        active={scope !== INBOX_SCOPE_FOR_YOU}
                        tooltip="See every report in the project, or a specific teammate's"
                        sideIcon={<IconChevronDown className="text-tertiary" />}
                    >
                        <span className="max-w-[160px] truncate">{rightLabel}</span>
                    </LemonButton>
                )}
            </MemberSelect>
        </div>
    )
}
