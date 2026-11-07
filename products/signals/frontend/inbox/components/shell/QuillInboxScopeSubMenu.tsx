import { useState } from 'react'

import { INBOX_SCOPE_CLAIMED_BY_YOU, INBOX_SCOPE_ENTIRE_PROJECT } from '../../types'
import { INBOX_SCOPE_CLAIMED_BY_YOU_LABEL, INBOX_SCOPE_ENTIRE_PROJECT_LABEL } from './inboxToolbarOptions'
import { QuillInboxSearchSubMenu, QuillInboxSearchRow } from './QuillInboxSearchSubMenu'
import { useInboxScopeFilter } from './useInboxScopeFilter'

const memberRowValue = (uuid: string): string => `member:${uuid}`

/**
 * The quill sibling of `InboxScopeFilter`, as a row of the filter menu. Whose reports the list shows is
 * not a filter: it never lights the funnel's dot, and Clear filters leaves it alone.
 */
export function QuillInboxScopeSubMenu(): JSX.Element {
    const {
        scope,
        isForYou,
        selectedTeammateUuid,
        triggerLabel,
        options,
        optionsLoading,
        userUuid,
        searchReviewers,
        pick,
        pickMember,
    } = useInboxScopeFilter()
    const [search, setSearch] = useState('')

    const changeSearch = (next: string): void => {
        setSearch(next)
        searchReviewers(next)
    }
    const pickAndReset = (select: () => void): void => {
        select()
        // `pick` already resets the reviewer search, so only the field needs clearing.
        setSearch('')
    }

    // Like the Lemon picker, you lead the list until a search reorders it.
    const members =
        !search && userUuid
            ? [...options].sort((a, b) => Number(b.uuid === userUuid) - Number(a.uuid === userUuid))
            : options
    const memberRows: QuillInboxSearchRow[] = members.map((member) => {
        const name = member.name || member.email
        return {
            value: memberRowValue(member.uuid),
            label: name,
            hint: member.trailing,
            onSelect: () => pickAndReset(() => pickMember(member.uuid, name)),
        }
    })

    const selectedValue =
        scope === INBOX_SCOPE_ENTIRE_PROJECT
            ? INBOX_SCOPE_ENTIRE_PROJECT
            : scope === INBOX_SCOPE_CLAIMED_BY_YOU
              ? INBOX_SCOPE_CLAIMED_BY_YOU
              : isForYou && userUuid
                ? memberRowValue(userUuid)
                : selectedTeammateUuid
                  ? memberRowValue(selectedTeammateUuid)
                  : null

    return (
        <QuillInboxSearchSubMenu
            label="Scope"
            value={triggerLabel}
            selectedValue={selectedValue}
            search={search}
            onSearchChange={changeSearch}
            searchPlaceholder="Search people"
            onOpenChange={(open) => {
                if (!open && search) {
                    changeSearch('')
                }
            }}
            groups={[
                {
                    key: 'scopes',
                    rows: [
                        {
                            value: INBOX_SCOPE_ENTIRE_PROJECT,
                            label: INBOX_SCOPE_ENTIRE_PROJECT_LABEL,
                            onSelect: () => pickAndReset(() => pick(INBOX_SCOPE_ENTIRE_PROJECT)),
                        },
                        {
                            value: INBOX_SCOPE_CLAIMED_BY_YOU,
                            label: INBOX_SCOPE_CLAIMED_BY_YOU_LABEL,
                            onSelect: () => pickAndReset(() => pick(INBOX_SCOPE_CLAIMED_BY_YOU)),
                        },
                    ],
                },
                {
                    key: 'people',
                    label: 'People',
                    note: optionsLoading
                        ? 'Loading…'
                        : members.length === 0
                          ? search
                              ? 'No matches'
                              : 'No users'
                          : undefined,
                    rows: memberRows,
                },
            ]}
            dataAttr="inbox-scope-filter"
        />
    )
}
