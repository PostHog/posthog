import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import {
    INBOX_REPORT_SECTION_DESCRIPTION,
    INBOX_REPORT_SECTION_KEYS,
    INBOX_REPORT_SECTION_LABEL,
    INBOX_REPORT_SECTION_TAG,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
} from '../../types'

/**
 * Multi-select report-state filter for the flat Reports list: one checkbox per state (Needs decision,
 * Review and merge, Resolved, Dismissed, plus Not actionable for staff). The open-work states are
 * selected by default (see DEFAULT_STATE_FILTER); an empty selection means every state, so the
 * trigger reads "All statuses" then.
 */
export function InboxStateFilter(): JSX.Element {
    const { isStaff } = useValues(inboxSceneLogic)
    const { stateFilter, visibleStateFilter } = useValues(inboxFiltersLogic)
    const { toggleState } = useActions(inboxFiltersLogic)
    const [visible, setVisible] = useState(false)

    const options = INBOX_REPORT_SECTION_KEYS.filter(
        (key) => isStaff || !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)
    )
    // Label from the visible selection: a shared link can carry the staff-only state, and the
    // trigger must not read "Not actionable" (or an inflated count) for a state whose checkbox the
    // dropdown hides and that does not narrow the list.
    const label =
        visibleStateFilter.length === 0
            ? 'All statuses'
            : visibleStateFilter.length === 1
              ? INBOX_REPORT_SECTION_LABEL[visibleStateFilter[0]]
              : `${visibleStateFilter.length} statuses`

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={visible}
            onVisibilityChange={setVisible}
            matchWidth={false}
            actionable
            placement="bottom-start"
            overlay={
                <div className="flex flex-col gap-px p-1">
                    {options.map((key) => {
                        const tag = INBOX_REPORT_SECTION_TAG[key]
                        return (
                            <LemonCheckbox
                                key={key}
                                size="small"
                                checked={stateFilter.includes(key)}
                                onChange={() => toggleState(key)}
                                className="rounded px-1.5 py-1 hover:bg-surface-secondary"
                                fullWidth
                                label={
                                    <span
                                        className="flex items-center gap-1.5"
                                        title={INBOX_REPORT_SECTION_DESCRIPTION[key]}
                                    >
                                        {INBOX_REPORT_SECTION_LABEL[key]}
                                        {tag && (
                                            <LemonTag type="completion" size="small">
                                                {tag}
                                            </LemonTag>
                                        )}
                                    </span>
                                }
                                data-attr={`inbox-filter-state-${key}`}
                            />
                        )
                    })}
                </div>
            }
        >
            <LemonButton size="small" type="secondary" data-attr="inbox-filter-state">
                {label}
            </LemonButton>
        </LemonDropdown>
    )
}
