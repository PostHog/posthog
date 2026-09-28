import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent, Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { type ExceptionData, StackTraceView } from './StackTraceView'

export interface ErrorDetailsEventData {
    uuid?: string
    distinct_id?: string
    timestamp?: string
    properties?: Record<string, unknown>
}

export interface ErrorDetailsSummaryData {
    occurrences?: number
    users?: number
    sessions?: number
    first_seen?: string | null
    last_seen?: string | null
    top_urls?: string[]
    top_browsers?: string[]
    top_os?: string[]
    top_libraries?: string[]
    top_library_versions?: string[]
    sample_session_ids?: string[]
}

export interface ErrorDetailsData {
    results?: ErrorDetailsEventData[]
    summary?: ErrorDetailsSummaryData
    _posthogUrl?: string
}

function firstString(value: unknown): string | undefined {
    if (typeof value === 'string') {
        return value
    }
    if (Array.isArray(value) && typeof value[0] === 'string') {
        return value[0]
    }
    return undefined
}

function extractExceptions(properties: Record<string, unknown>): ExceptionData[] {
    if (Array.isArray(properties.$exception_list) && properties.$exception_list.length > 0) {
        return properties.$exception_list as ExceptionData[]
    }

    const type = firstString(properties.$exception_types)
    const value = firstString(properties.$exception_values)
    if (type || value) {
        return [{ type: type ?? 'Error', value: value ?? '' }]
    }

    return []
}

function joinValues(values: string[] | undefined): string | undefined {
    return values && values.length > 0 ? values.join(', ') : undefined
}

function ErrorEventsSummaryView({ summary }: { summary: ErrorDetailsSummaryData }): ReactElement {
    return (
        <div className="p-4">
            <Card>
                <CardContent>
                    <DescriptionList
                        items={[
                            { label: 'Occurrences', value: summary.occurrences ?? 0 },
                            { label: 'Users', value: summary.users ?? 0 },
                            { label: 'Sessions', value: summary.sessions ?? 0 },
                            {
                                label: 'First seen',
                                value: summary.first_seen ? formatDate(summary.first_seen, true) : undefined,
                            },
                            {
                                label: 'Last seen',
                                value: summary.last_seen ? formatDate(summary.last_seen, true) : undefined,
                            },
                            { label: 'Top URLs', value: joinValues(summary.top_urls) },
                            { label: 'Browsers', value: joinValues(summary.top_browsers) },
                            { label: 'OS', value: joinValues(summary.top_os) },
                            { label: 'Libraries', value: joinValues(summary.top_libraries) },
                            { label: 'Library versions', value: joinValues(summary.top_library_versions) },
                        ]}
                    />
                </CardContent>
            </Card>
        </div>
    )
}

export function ErrorDetailsView({ data }: { data: ErrorDetailsData }): ReactElement {
    const events = data.results ?? (Array.isArray(data) ? data : [])

    if (data.summary) {
        return <ErrorEventsSummaryView summary={data.summary} />
    }

    if (events.length === 0) {
        return (
            <div className="p-4">
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>No error events</EmptyTitle>
                        <EmptyDescription>
                            No error events found for this issue in the selected time range
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    // Show the first (most recent) event
    const event = events[0]
    const properties = event.properties ?? {}
    const exceptions = extractExceptions(properties)

    const exceptionType = firstString(properties.$exception_types) ?? exceptions[0]?.type ?? 'Error'
    const exceptionMessage = firstString(properties.$exception_values) ?? exceptions[0]?.value ?? ''
    const isSynthetic =
        properties.$exception_synthetic === true || exceptions.some((exception) => exception.mechanism?.synthetic)

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="destructive">{exceptionType}</Badge>
                        {isSynthetic && <Badge>Synthetic</Badge>}
                    </div>
                    <span className="text-sm">{exceptionMessage}</span>
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                ...(event.timestamp
                                    ? [{ label: 'Timestamp', value: formatDate(event.timestamp, true) }]
                                    : []),
                                ...(event.distinct_id ? [{ label: 'Distinct ID', value: event.distinct_id }] : []),
                                ...(properties.$browser
                                    ? [
                                          {
                                              label: 'Browser',
                                              value: `${properties.$browser}${properties.$browser_version ? ` ${properties.$browser_version}` : ''}`,
                                          },
                                      ]
                                    : []),
                                ...(properties.$os
                                    ? [
                                          {
                                              label: 'OS',
                                              value: `${properties.$os}${properties.$os_version ? ` ${properties.$os_version}` : ''}`,
                                          },
                                      ]
                                    : []),
                                ...(properties.$lib ? [{ label: 'Library', value: properties.$lib as string }] : []),
                                ...(properties.$current_url
                                    ? [{ label: 'URL', value: properties.$current_url as string }]
                                    : []),
                                ...(properties.$session_id
                                    ? [{ label: 'Session ID', value: properties.$session_id as string }]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                {exceptions.length > 0 && <StackTraceView exceptions={exceptions} />}

                {events.length > 1 && (
                    <span className="text-xs text-muted-foreground">
                        Showing most recent event. {events.length - 1} more event{events.length - 1 === 1 ? '' : 's'} in
                        this issue.
                    </span>
                )}
            </div>
        </div>
    )
}
