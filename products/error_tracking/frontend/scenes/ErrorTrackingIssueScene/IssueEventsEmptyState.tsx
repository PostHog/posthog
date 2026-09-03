import { IconCalendar, IconFilter } from '@posthog/icons'

import { Button, Heading, Text } from 'lib/ui/quill'

export interface IssueEventsEmptyStateProps {
    nextDateRangeLabel: string | null
    hasActiveFilters: boolean
    loading: boolean
    onIncreaseDateRange: () => void
    onClearFilters: () => void
}

export function IssueEventsEmptyState({
    nextDateRangeLabel,
    hasActiveFilters,
    loading,
    onIncreaseDateRange,
    onClearFilters,
}: IssueEventsEmptyStateProps): JSX.Element {
    const detail = hasActiveFilters
        ? nextDateRangeLabel
            ? 'Try a wider date range or remove filters.'
            : 'Remove filters to see more exceptions.'
        : nextDateRangeLabel
          ? 'Try a wider date range to see earlier exceptions.'
          : 'No exceptions match this date range.'

    return (
        <div className="flex min-h-64 flex-1 items-center justify-center px-4 py-8 text-center">
            <div className="flex max-w-md flex-col items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-full bg-fill-secondary text-secondary">
                    <IconCalendar className="size-5" />
                </div>
                <div className="flex flex-col gap-1">
                    <Heading size="base">No exceptions found</Heading>
                    <Text size="sm" variant="muted">
                        {detail}
                    </Text>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-2">
                    {nextDateRangeLabel && (
                        <Button variant="outline" loading={loading} onClick={onIncreaseDateRange}>
                            <IconCalendar />
                            Show last {nextDateRangeLabel}
                        </Button>
                    )}
                    {hasActiveFilters && (
                        <Button variant="outline" disabled={loading} onClick={onClearFilters}>
                            <IconFilter />
                            Remove filters
                        </Button>
                    )}
                </div>
            </div>
        </div>
    )
}
