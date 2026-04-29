import type { ReactElement } from 'react'

import { Badge, Card, DescriptionList, EmptyState, formatDate, Stack } from '@posthog/mosaic'

import { type ExceptionData, StackTraceView } from './StackTraceView'

export interface ErrorDetailsEventData {
    uuid?: string
    distinct_id?: string
    timestamp?: string
    properties?: Record<string, unknown>
}

export interface ErrorDetailsData {
    results?: ErrorDetailsEventData[]
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

export function ErrorDetailsView({ data }: { data: ErrorDetailsData }): ReactElement {
    const events = data.results ?? (Array.isArray(data) ? data : [])

    if (events.length === 0) {
        return (
            <div className="p-4">
                <EmptyState
                    title="No error events"
                    description="No error events found for this issue in the selected time range"
                />
            </div>
        )
    }

    // Show the first (most recent) event
    const event = events[0]
    const properties = event.properties ?? {}
    const exceptions = extractExceptions(properties)

    const exceptionType = firstString(properties.$exception_types) ?? exceptions[0]?.type ?? 'Error'
    const exceptionMessage = firstString(properties.$exception_values) ?? exceptions[0]?.value ?? ''

    return (
        <div className="p-4">
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="danger" size="md">
                            {exceptionType}
                        </Badge>
                    </div>
                    <span className="text-sm text-text-primary">{exceptionMessage}</span>
                </Stack>

                <Card padding="md">
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
                </Card>

                {exceptions.length > 0 && <StackTraceView exceptions={exceptions} />}

                {events.length > 1 && (
                    <span className="text-xs text-text-secondary">
                        Showing most recent event. {events.length - 1} more event{events.length - 1 === 1 ? '' : 's'} in
                        this issue.
                    </span>
                )}
            </Stack>
        </div>
    )
}
