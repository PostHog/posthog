import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { compactNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { eventsSourceLogic } from './components/EventsTable/eventsSourceLogic'
import { EventsTable, getEventMarkerColor } from './components/EventsTable/EventsTable'
import { ExceptionCard } from './components/ExceptionCard'
import { errorTrackingIssueSceneLogic } from './scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

export type ErrorTrackingIssueNotebookWidgetAttributes = {
    id: string
    view?: string
}

function ErrorTrackingIssueMetadata({
    attributes,
}: NotebookNodeProps<ErrorTrackingIssueNotebookWidgetAttributes>): null {
    const { issue } = useValues(errorTrackingIssueSceneLogic({ id: attributes.id }))
    const { setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(issue?.name || issue?.description || 'Error tracking issue')
        setTitleStatus(
            issue?.status
                ? {
                      label: capitalizeFirstLetter(issue.status.replaceAll('_', ' ')),
                      type: issue.status === 'resolved' ? 'success' : issue.status === 'active' ? 'danger' : 'default',
                  }
                : null
        )
    }, [issue, setTitlePlaceholder, setTitleStatus])

    return null
}

function ErrorTrackingIssueLoading(): JSX.Element {
    return (
        <div className="p-3">
            <LemonSkeleton className="h-6 w-full" />
        </div>
    )
}

function ErrorTrackingIssueSummary({
    attributes,
}: NotebookNodeProps<ErrorTrackingIssueNotebookWidgetAttributes>): JSX.Element {
    const logic = errorTrackingIssueSceneLogic({ id: attributes.id })
    const { aggregations, firstSeen, issue, issueLoading } = useValues(logic)

    if (!issue && issueLoading) {
        return <ErrorTrackingIssueLoading />
    }
    if (!issue) {
        return <NotFound object="error tracking issue" />
    }

    return (
        <BindLogic logic={errorTrackingIssueSceneLogic} props={{ id: attributes.id }}>
            <ErrorTrackingIssueMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3 text-sm">
                {firstSeen ? (
                    <span>
                        <span className="text-secondary">First seen: </span>
                        <TZLabel time={firstSeen} />
                    </span>
                ) : null}
                <span>{compactNumber(aggregations?.occurrences || 0)} occurrences</span>
                <span>{compactNumber(aggregations?.users || 0)} users</span>
            </div>
        </BindLogic>
    )
}

export function ErrorTrackingIssueDetail({
    attributes,
}: NotebookNodeProps<ErrorTrackingIssueNotebookWidgetAttributes>): JSX.Element {
    const logic = errorTrackingIssueSceneLogic({ id: attributes.id })
    const { initialEvent, initialEventLoading, issue, issueLoading, selectedEvent, summary } = useValues(logic)
    const detailEvent = selectedEvent || initialEvent || undefined

    if (!issue && !issueLoading) {
        return <NotFound object="error tracking issue" />
    }

    return (
        <BindLogic logic={errorTrackingIssueSceneLogic} props={{ id: attributes.id }}>
            <ErrorTrackingIssueMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="min-h-96 p-3">
                <ExceptionCard
                    issueId={attributes.id}
                    issueName={issue?.name || null}
                    event={detailEvent}
                    eventMarkerColor={
                        detailEvent
                            ? getEventMarkerColor(detailEvent.uuid, summary?.first_event_uuid, summary?.last_event_uuid)
                            : undefined
                    }
                    loading={issueLoading || initialEventLoading}
                />
            </div>
        </BindLogic>
    )
}

function ErrorTrackingIssueActivity({
    attributes,
}: NotebookNodeProps<ErrorTrackingIssueNotebookWidgetAttributes>): JSX.Element {
    const logic = errorTrackingIssueSceneLogic({ id: attributes.id })
    const { issue, issueLoading } = useValues(logic)

    if (!issue && !issueLoading) {
        return <NotFound object="error tracking issue" />
    }

    return (
        <BindLogic logic={errorTrackingIssueSceneLogic} props={{ id: attributes.id }}>
            <ErrorTrackingIssueMetadata attributes={attributes} updateAttributes={() => {}} />
            <ErrorTrackingIssueActivityTable />
        </BindLogic>
    )
}

function ErrorTrackingIssueActivityTable(): JSX.Element {
    const { eventsQuery, eventsQueryKey, selectedEvent, summary } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const dataSource = eventsSourceLogic({ query: eventsQuery, queryKey: eventsQueryKey })
    const { items, itemsLoading, canLoadNextData } = useValues(dataSource)
    const { loadNextData } = useActions(dataSource)

    return (
        <div className="h-96 overflow-auto p-3">
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
        </div>
    )
}

export const ERROR_TRACKING_ISSUE_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<
    ErrorTrackingIssueNotebookWidgetAttributes,
    'ErrorTrackingIssue'
>('ErrorTrackingIssue', {
    summary: ErrorTrackingIssueSummary,
    activity: ErrorTrackingIssueActivity,
})
