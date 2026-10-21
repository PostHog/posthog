import { IconCalendar, IconFilter } from '@posthog/icons'

import { Button, Heading, Spinner, Text } from 'lib/ui/quill'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { LinkedLogsCheckStatus } from './linkedLogsCheckLogic'

export interface IssueEventsEmptyStateProps {
    nextDateRangeLabel: string | null
    hasActiveFilters: boolean
    loading: boolean
    onIncreaseDateRange: () => void
    onClearFilters: () => void
    /** Set while the list checks older exceptions for linked logs, or after it paused that check. */
    linkedLogsCheck?: {
        status: LinkedLogsCheckStatus
        checkedCount: number
        onCheckOlder: () => void
    }
}

export function IssueEventsEmptyState({
    nextDateRangeLabel,
    hasActiveFilters,
    loading,
    onIncreaseDateRange,
    onClearFilters,
    linkedLogsCheck,
}: IssueEventsEmptyStateProps): JSX.Element {
    const checkStatus = linkedLogsCheck?.status
    const checkedCount = <span translate="no">{humanFriendlyNumber(linkedLogsCheck?.checkedCount ?? 0)}</span>

    const title =
        checkStatus === 'checking'
            ? 'Looking for exceptions with logs'
            : checkStatus === 'paused'
              ? 'No exceptions with logs yet'
              : 'No exceptions found'
    // Each state renders its own element, so a page translation extension never sees React rewrite a translated
    // text node in place.
    const detail =
        checkStatus === 'checking' ? (
            <Text key="checking" size="sm" variant="muted">
                Checked {checkedCount} exceptions so far.
            </Text>
        ) : checkStatus === 'paused' ? (
            <Text key="paused" size="sm" variant="muted">
                None of the {checkedCount} most recent exceptions have logs.
            </Text>
        ) : (
            <Text key="filters" size="sm" variant="muted">
                {hasActiveFilters
                    ? nextDateRangeLabel
                        ? 'Try a wider date range or remove filters.'
                        : 'Remove filters to see more exceptions.'
                    : nextDateRangeLabel
                      ? 'Try a wider date range to see earlier exceptions.'
                      : 'No exceptions match this date range.'}
            </Text>
        )

    return (
        <div className="flex min-h-64 flex-1 items-center justify-center px-4 py-8 text-center">
            <div className="flex max-w-md flex-col items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-full bg-fill-secondary text-secondary">
                    {checkStatus === 'checking' ? <Spinner /> : <IconCalendar className="size-5" />}
                </div>
                <div className="flex flex-col gap-1">
                    <Heading key={title} size="base">
                        {title}
                    </Heading>
                    {detail}
                </div>
                <div className="flex flex-wrap items-center justify-center gap-2">
                    {checkStatus === 'paused' && (
                        <Button
                            variant="outline"
                            loading={loading}
                            onClick={linkedLogsCheck?.onCheckOlder}
                            data-attr="error-tracking-issue-check-older-exceptions"
                        >
                            Check older exceptions
                        </Button>
                    )}
                    {!linkedLogsCheck && nextDateRangeLabel && (
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
