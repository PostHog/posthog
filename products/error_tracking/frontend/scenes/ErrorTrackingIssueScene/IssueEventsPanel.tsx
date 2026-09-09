import { useActions, useValues } from 'kea'
import { PropsWithChildren, useEffect, useRef } from 'react'

import { ErrorEventType } from 'lib/components/Errors/types'

import { eventsSourceLogic } from '../../components/EventsTable/eventsSourceLogic'
import { EventsTable, EventsTableLoading } from '../../components/EventsTable/EventsTable'
import { issueFilterPreviewLogic } from '../../components/IssueFilterPreview/issueFilterPreviewLogic'
import { IssueFilterPreviewPanel } from '../../components/IssueFilterPreview/IssueFilterPreviewPanel'
import { getNextErrorTrackingDateRange } from '../../components/IssueFilters/DateRange'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssueEventsEmptyState } from './IssueEventsEmptyState'
import { IssueEventsToolbar } from './IssueEventsToolbar'

export function IssueEventsPanel(): JSX.Element {
    const { issueFingerprintsLoading } = useValues(errorTrackingIssueSceneLogic)

    if (issueFingerprintsLoading) {
        return (
            <IssueEventsLayout loading>
                <EventsTableLoading />
            </IssueEventsLayout>
        )
    }

    return <LoadedIssueEventsPanel />
}

function LoadedIssueEventsPanel(): JSX.Element {
    const { eventsQuery, eventsQueryKey, selectedEvent, summary } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent, setMobileDetailOpen } = useActions(errorTrackingIssueSceneLogic)
    const { dateRange } = useValues(issueFiltersLogic)
    const { hasActiveFilters } = useValues(issueFilterPreviewLogic)
    const { clearNonDateFilters } = useActions(issueFilterPreviewLogic)
    const { setDateRange } = useActions(issueFiltersLogic)
    const dataSource = eventsSourceLogic({ query: eventsQuery, queryKey: eventsQueryKey })
    const { items, itemsLoading, canLoadNextData } = useValues(dataSource)
    const { loadData, loadNextData } = useActions(dataSource)
    const nextDateRange = getNextErrorTrackingDateRange(dateRange)
    const previousEventsQueryKey = useRef(eventsQueryKey)

    useEffect(() => {
        if (itemsLoading) {
            return
        }

        const queryChanged = previousEventsQueryKey.current !== eventsQueryKey
        previousEventsQueryKey.current = eventsQueryKey
        const nextSelection = getListSelection(items, selectedEvent, canLoadNextData, queryChanged)
        if (nextSelection !== selectedEvent) {
            selectEvent(nextSelection)
        }
        if (!nextSelection) {
            setMobileDetailOpen(false)
        }
    }, [items, itemsLoading, canLoadNextData, eventsQueryKey, selectEvent, selectedEvent, setMobileDetailOpen])

    return (
        <IssueEventsLayout
            loading={itemsLoading}
            onReload={() => loadData('force_blocking')}
            onScrollNearEnd={() => {
                if (canLoadNextData && !itemsLoading) {
                    loadNextData()
                }
            }}
        >
            {!itemsLoading && items.length === 0 ? (
                <IssueEventsEmptyState
                    nextDateRangeLabel={nextDateRange?.label ?? null}
                    hasActiveFilters={hasActiveFilters}
                    loading={itemsLoading}
                    onIncreaseDateRange={() => {
                        if (nextDateRange) {
                            setDateRange(nextDateRange.dateRange)
                        }
                    }}
                    onClearFilters={clearNonDateFilters}
                />
            ) : (
                <EventsTable
                    items={items}
                    loading={itemsLoading}
                    hasMore={canLoadNextData}
                    selectedEvent={selectedEvent}
                    firstEventUuid={summary?.first_event_uuid}
                    lastEventUuid={summary?.last_event_uuid}
                    onEventSelect={selectEvent}
                    onLoadMore={loadNextData}
                />
            )}
        </IssueEventsLayout>
    )
}

export function getListSelection(
    items: ErrorEventType[],
    selectedEvent: ErrorEventType | null,
    canLoadMore: boolean,
    queryChanged: boolean
): ErrorEventType | null {
    const matchedEvent = selectedEvent ? items.find((item) => item.uuid === selectedEvent.uuid) : undefined
    if (matchedEvent) {
        return matchedEvent
    }
    // A later page of the same query may hold a timestamp-linked exception older than the first
    // 100 rows. A new query cannot make that claim, so filter changes reconcile immediately.
    if (selectedEvent && canLoadMore && !queryChanged) {
        return selectedEvent
    }
    return items[0] ?? null
}

function IssueEventsLayout({
    children,
    loading,
    onReload,
    onScrollNearEnd,
}: PropsWithChildren<{
    loading: boolean
    onReload?: () => void
    onScrollNearEnd?: () => void
}>): JSX.Element {
    return (
        <div className="flex h-full min-h-0 flex-col">
            <IssueFilterPreviewPanel className="flex min-h-0 flex-1 flex-col" onScrollNearEnd={onScrollNearEnd}>
                <IssueEventsToolbar loading={loading} onReload={onReload} />
                {children}
            </IssueFilterPreviewPanel>
        </div>
    )
}
