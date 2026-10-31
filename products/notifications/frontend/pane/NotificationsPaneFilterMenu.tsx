import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TodayFilterMenuTrigger } from '~/layout/today/TodayFilterMenuTrigger'
import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'

import { NOTIFICATION_CATEGORY_LABELS, NotificationCategory } from './notificationKinds'
import {
    DEFAULT_NOTIFICATIONS_PANE_FILTERS,
    NotificationsCategoryFilter,
    NotificationsPaneFilters,
    NotificationsProjectFilter,
    NotificationsReadFilter,
    notificationsPaneFiltersActive,
} from './notificationsPaneFilters'

const READ_OPTIONS: { value: NotificationsReadFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'unread', label: 'Unread only' },
]

const CATEGORY_OPTIONS: { value: NotificationsCategoryFilter; label: string }[] = [
    { value: 'any', label: 'Any category' },
    ...Object.entries(NOTIFICATION_CATEGORY_LABELS).map(([value, label]) => ({
        value: value as NotificationCategory,
        label,
    })),
]

const PROJECT_OPTIONS: { value: NotificationsProjectFilter; label: string }[] = [
    { value: 'all', label: 'All projects' },
    { value: 'current', label: 'This project' },
]

interface NotificationsPaneFilterMenuProps {
    filters: NotificationsPaneFilters
    onChange: (filters: NotificationsPaneFilters) => void
    defaultOpen?: boolean
}

export function NotificationsPaneFilterMenu({
    filters,
    onChange,
    defaultOpen,
}: NotificationsPaneFilterMenuProps): JSX.Element {
    const active = notificationsPaneFiltersActive(filters)
    return (
        <DropdownMenu defaultOpen={defaultOpen}>
            <TodayFilterMenuTrigger active={active} dataAttr="notifications-pane-filter" />
            <DropdownMenuContent align="end">
                <TodayRecentRadioSubmenu
                    label="Show"
                    options={READ_OPTIONS}
                    value={filters.read}
                    defaultValue={DEFAULT_NOTIFICATIONS_PANE_FILTERS.read}
                    onChange={(read) => onChange({ ...filters, read })}
                    dataAttr="notifications-pane-filter-read"
                />
                <TodayRecentRadioSubmenu
                    label="Category"
                    options={CATEGORY_OPTIONS}
                    value={filters.category}
                    defaultValue={DEFAULT_NOTIFICATIONS_PANE_FILTERS.category}
                    onChange={(category) => onChange({ ...filters, category })}
                    dataAttr="notifications-pane-filter-category"
                />
                <TodayRecentRadioSubmenu
                    label="Project"
                    options={PROJECT_OPTIONS}
                    value={filters.project}
                    defaultValue={DEFAULT_NOTIFICATIONS_PANE_FILTERS.project}
                    onChange={(project) => onChange({ ...filters, project })}
                    dataAttr="notifications-pane-filter-project"
                />
                {active && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => onChange(DEFAULT_NOTIFICATIONS_PANE_FILTERS)}
                            data-attr="notifications-pane-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
