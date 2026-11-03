import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonDropdown } from '@posthog/lemon-ui'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { InboxReportFilters } from './InboxReportFilters'

/**
 * The Reports filters folded behind one button, for a container too narrow to show them in a row.
 * Changes apply as they are made, the same as the row. The badge counts only the filters that differ
 * from their default, so the default view shows no badge.
 */
export function InboxFiltersPanel(): JSX.Element {
    const { nonDefaultReportFilterCount: count } = useValues(inboxFiltersLogic)
    const { clearFilters } = useActions(inboxFiltersLogic)
    const [visible, setVisible] = useState(false)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={visible}
            onVisibilityChange={setVisible}
            matchWidth={false}
            actionable
            placement="bottom-start"
            overlay={
                <div className="flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-2 p-2">
                    <InboxReportFilters layout="panel" />
                    <LemonDivider className="my-0" />
                    <LemonButton
                        size="small"
                        type="tertiary"
                        onClick={clearFilters}
                        disabledReason={count === 0 ? 'The filters are already at their defaults' : undefined}
                        data-attr="inbox-filters-reset"
                    >
                        Reset to default
                    </LemonButton>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconFilter />}
                sideIcon={count > 0 ? <LemonBadge.Number count={count} size="small" /> : undefined}
                aria-label={count > 0 ? `Filters, ${count} changed` : 'Filters'}
                // pinned: autocapture selector. Compact filter usage insights filter clicks on this data-attr.
                data-attr="inbox-filters-panel"
            >
                Filters
            </LemonButton>
        </LemonDropdown>
    )
}
