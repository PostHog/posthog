import { ErrorEventType } from 'lib/components/Errors/types'

import { ErrorTrackingIssueEventsQuery, EventsQuery } from '~/queries/schema/schema-general'

import { createDataSourceLogic } from '../DataSourceTable'

export interface EventsSourceProps {
    queryKey: string
    query: EventsQuery | ErrorTrackingIssueEventsQuery
}

type EventsQueryPerson = ErrorEventType['person'] & { distinct_id: string }

type EventsQueryRow = [
    event: Pick<ErrorEventType, 'uuid' | 'properties'>,
    timestamp: ErrorEventType['timestamp'],
    person: EventsQueryPerson,
    // Only an ErrorTrackingIssueEventsQuery that checks linked logs returns this column.
    linkedLogs?: boolean | null,
]

function rowToRecord([event, timestamp, person, linkedLogs]: EventsQueryRow): ErrorEventType {
    return {
        event: '$exception',
        uuid: event.uuid,
        timestamp,
        person,
        distinct_id: event.properties.distinct_id || person.distinct_id,
        properties: event.properties,
        ...(linkedLogs !== undefined ? { linkedLogs } : {}),
    }
}

export const eventsSourceLogic = createDataSourceLogic<EventsSourceProps, ErrorEventType, EventsQueryRow>(
    () => ['products', 'error_tracking', 'components', 'EventsTable', 'eventsSourceLogic'],
    rowToRecord
)
