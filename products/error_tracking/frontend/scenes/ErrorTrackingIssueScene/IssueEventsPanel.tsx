import { useActions, useValues } from 'kea'
import { PropsWithChildren } from 'react'

import { IconRefresh } from '@posthog/icons'

import { Button, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { eventsSourceLogic } from '../../components/EventsTable/eventsSourceLogic'
import { EventsTable, EventsTableLoading } from '../../components/EventsTable/EventsTable'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

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
    const { eventsQuery, eventsQueryKey, selectedEvent, issueFingerprints, summary } =
        useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const dataSource = eventsSourceLogic({ query: eventsQuery, queryKey: eventsQueryKey })
    const { items, itemsLoading, canLoadNextData } = useValues(dataSource)
    const { loadData, loadNextData } = useActions(dataSource)

    return (
        <IssueEventsLayout
            loading={itemsLoading}
            onReload={loadData}
            onScrollNearEnd={() => {
                if (canLoadNextData && !itemsLoading) {
                    loadNextData()
                }
            }}
        >
            {issueFingerprints.length === 0 ? (
                <div className="px-2 py-3 text-sm text-muted-foreground">No exceptions found for this issue.</div>
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
                        <div className="flex w-full flex-col gap-1">
                            <div className="flex w-full flex-wrap items-center gap-1">
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="outline"
                                                size="icon"
                                                loading={loading}
                                                aria-label="Reload exceptions"
                                                onClick={onReload}
                                            />
                                        }
                                    >
                                        <IconRefresh />
                                    </TooltipTrigger>
                                    <TooltipContent>Reload exceptions</TooltipContent>
                                </Tooltip>
                                <ErrorFilters.DateRange />
                                <div className="ml-auto shrink-0">
                                    <ErrorFilters.InternalAccounts />
                                </div>
                            </div>
                            <div className="flex w-full flex-wrap items-center gap-1">
                                <ErrorFilters.Search
                                    className="w-auto min-w-40 flex-1 shrink"
                                    placeholder="Search exceptions"
                                />
                                <ErrorFilters.FilterGroup />
                            </div>
                        </div>
                    </ErrorFilters.Root>
                </div>
                {children}
            </Metadata>
        </div>
    )
}
