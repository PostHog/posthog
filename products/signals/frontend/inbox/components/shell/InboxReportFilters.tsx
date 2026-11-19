import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { INBOX_CREATED_WINDOW_OPTIONS } from '../../filterOptions'
import { InboxCreatedWindow, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { InboxPriorityFilter } from './InboxPriorityFilter'
import { InboxSourceFilter } from './InboxSourceFilter'
import { InboxStateFilter } from './InboxStateFilter'

const ANY_TIME = null
const CREATED_WINDOW_SELECT_OPTIONS: { value: InboxCreatedWindow | null; label: string }[] = [
    { value: ANY_TIME, label: 'Any time' },
    ...INBOX_CREATED_WINDOW_OPTIONS.map(({ value, label }) => ({ value, label })),
]

function createdWindowLabel(window: InboxCreatedWindow | null): string {
    return CREATED_WINDOW_SELECT_OPTIONS.find((option) => option.value === window)?.label ?? 'Any time'
}

function PanelField({ label, children }: { label: string; children: JSX.Element }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-secondary">{label}</span>
            {children}
        </div>
    )
}

/**
 * What narrows the report list: report state, then priority, then the created-in window, then source.
 * Filter state is persisted via `inboxFiltersLogic`, and the list reloads on change.
 *
 * Source goes last because its label grows with the selected scout name. Anywhere earlier, a long name
 * pushes the controls after it to the right.
 *
 * Sort and reviewer scope are deliberately not here. Sort orders the list rather than narrowing it,
 * and scope picks whose inbox this is, so both sit after a divider at the end of the row.
 */
export function InboxReportFilters({ layout = 'row' }: { layout?: 'row' | 'panel' }): JSX.Element {
    const { timeWindowAvailable, createdWindow, sourceFilterAvailable } = useValues(inboxFiltersLogic)
    const { setCreatedWindow } = useActions(inboxFiltersLogic)
    const panel = layout === 'panel'
    const field = (label: string, control: JSX.Element): JSX.Element =>
        panel ? <PanelField label={label}>{control}</PanelField> : control

    return (
        <div className={panel ? 'flex flex-col gap-2' : 'flex flex-wrap items-center gap-2'}>
            {field('Status', <InboxStateFilter />)}
            {field('Priority', <InboxPriorityFilter />)}
            {timeWindowAvailable &&
                field(
                    'Created',
                    <LemonSelect
                        size="small"
                        value={createdWindow}
                        onChange={(window) => setCreatedWindow(window)}
                        options={CREATED_WINDOW_SELECT_OPTIONS}
                        icon={<IconCalendar />}
                        tooltip={panel ? undefined : `Created: ${createdWindowLabel(createdWindow)}`}
                        // The window value ("7d") doubles as the short label in a narrow container.
                        renderButtonContent={(leaf) =>
                            panel ? (
                                (leaf?.label ?? 'Any time')
                            ) : (
                                <>
                                    <span className="@2xl:hidden">{leaf?.value ?? 'Any time'}</span>
                                    <span className="hidden @2xl:inline">{leaf?.label ?? 'Any time'}</span>
                                </>
                            )
                        }
                        data-attr="inbox-filter-created-window"
                    />
                )}
            {sourceFilterAvailable && field('Source', <InboxSourceFilter />)}
        </div>
    )
}
