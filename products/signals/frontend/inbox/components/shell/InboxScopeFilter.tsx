import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { INBOX_SCOPE_CLAIMED_BY_YOU, INBOX_SCOPE_ENTIRE_PROJECT } from '../../types'
import {
    INBOX_SCOPE_CLAIMED_BY_YOU_LABEL,
    INBOX_SCOPE_ENTIRE_PROJECT_LABEL,
    INBOX_SCOPE_HELP,
} from './inboxToolbarOptions'
import { useInboxScopeFilter } from './useInboxScopeFilter'

/**
 * Single-dropdown reviewer scope for the flat Reports list: one trigger that names the current
 * scope and opens the shared people picker with "Entire project", "Claimed by you" and each teammate.
 * Selecting yourself uses the "For you" scope. A user with no reports suggested to them is
 * auto-switched to "Entire project" (see `shouldDefaultToEntireProject`). Scope is persisted via
 * `inboxFiltersLogic`; teammates come from its shared `availableReviewers` loader.
 */
export function InboxScopeFilter(): JSX.Element {
    const { selectedTeammateUuid, triggerLabel, options, optionsLoading, searchReviewers, pick, pickMember } =
        useInboxScopeFilter()

    return (
        <MemberSelect
            value={selectedTeammateUuid}
            defaultLabel={INBOX_SCOPE_ENTIRE_PROJECT_LABEL}
            options={options}
            optionsLoading={optionsLoading}
            onSearch={searchReviewers}
            extraOptions={[
                { label: INBOX_SCOPE_CLAIMED_BY_YOU_LABEL, onClick: () => pick(INBOX_SCOPE_CLAIMED_BY_YOU) },
            ]}
            onChange={() => pick(INBOX_SCOPE_ENTIRE_PROJECT)}
            onSelectOption={pickMember}
        >
            {() => (
                <LemonButton
                    size="small"
                    type="secondary"
                    tooltip={INBOX_SCOPE_HELP}
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
