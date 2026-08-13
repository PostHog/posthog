import { useActions, useValues } from 'kea'
import { PropsWithChildren, useEffect } from 'react'

import { IconRefresh } from '@posthog/icons'

import { ErrorEventType } from 'lib/components/Errors/types'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { eventsSourceLogic } from '../../components/EventsTable/eventsSourceLogic'
import { EventsTable, EventsTableLoading } from '../../components/EventsTable/EventsTable'
import { issueFilterPreviewLogic } from '../../components/IssueFilterPreview/issueFilterPreviewLogic'
import { ErrorFilters } from '../../components/IssueFilters'
import { getNextErrorTrackingDateRange } from '../../components/IssueFilters/DateRange'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { Metadata } from '../../components/IssueMetadata'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssueEventsEmptyState } from './IssueEventsEmptyState'

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

    useEffect(() => {
        if (itemsLoading) {
            return
        }

        const nextSelection = getListSelection(items, selectedEvent, canLoadNextData)
        if (nextSelection !== selectedEvent) {
            selectEvent(nextSelection)
        }
        if (!nextSelection) {
            setMobileDetailOpen(false)
        }
    }, [items, itemsLoading, canLoadNextData, selectEvent, selectedEvent, setMobileDetailOpen])

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
    canLoadMore: boolean
): ErrorEventType | null {
    const matchedEvent = selectedEvent ? items.find((item) => item.uuid === selectedEvent.uuid) : undefined
    if (matchedEvent) {
        return matchedEvent
    }
    // The selection isn't on the loaded page, but a later page may still hold it — e.g. a
    // timestamp-linked exception older than the first 100 rows. Keep it until the list is fully
    // loaded rather than swapping in the newest event and rewriting the URL away from the link.
    if (selectedEvent && canLoadMore) {
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
            <Metadata className="flex min-h-0 flex-1 flex-col" onScrollNearEnd={onScrollNearEnd}>
                <div className="sticky top-0 z-10 shrink-0 border-y border-primary bg-surface-primary px-2 py-2">
                    <ErrorFilters.Root className="w-full">
                        <ErrorFilters.FilterGroup
                            iconOnly
                            renderControls={({ filterPicker, activeFilters }) => (
                                <div className="flex w-full flex-col gap-2">
                                    <div className="flex w-full flex-nowrap items-center gap-2">
                                        <Tooltip>
                                            <TooltipTrigger
                                                render={
                                                    <Button
                                                        variant="outline"
                                                        size="icon"
                                                        loading={loading}
                                                        aria-label="Reload exceptions"
                                                        onClick={() => onReload?.()}
                                                    />
                                                }
                                            >
                                                <IconRefresh />
                                            </TooltipTrigger>
                                            <TooltipContent>Reload exceptions</TooltipContent>
                                        </Tooltip>
                                        <ErrorFilters.DateRange />
                                        <ErrorFilters.Search
                                            className="w-auto min-w-40 flex-1 shrink"
                                            placeholder="Search exceptions"
                                            endAddon={filterPicker}
                                        />
                                        <div className="shrink-0">
                                            <ErrorFilters.InternalAccounts />
                                        </div>
                                    </div>
                                    {activeFilters ? <div>{activeFilters}</div> : null}
                                </div>
                            )}
                        />
                    </ErrorFilters.Root>
                </div>
                {children}
            </Metadata>
        </div>
    )
}
