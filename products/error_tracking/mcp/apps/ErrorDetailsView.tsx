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

function extractExceptions(properties: Record<string, unknown>): ExceptionData[] {
    // Primary source: $exception_list (structured exception data)
    if (Array.isArray(properties.$exception_list) && properties.$exception_list.length > 0) {
        return properties.$exception_list as ExceptionData[]
    }

    // Fallback: construct from individual properties
    const type = properties.$exception_type as string | undefined
    const value = (properties.$exception_message ?? properties.$exception_value) as string | undefined
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

    const exceptionType = (properties.$exception_type as string) ?? exceptions[0]?.type ?? 'Error'
    const exceptionMessage = (properties.$exception_message as string) ?? exceptions[0]?.value ?? ''

    return (
        <div className="p-4">
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="danger" size="md">
                            {exceptionType}
                        </Badge>
                        {properties.$exception_synthetic && (
                            <Badge variant="neutral" size="sm">
                                Synthetic
                            </Badge>
                        )}
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
