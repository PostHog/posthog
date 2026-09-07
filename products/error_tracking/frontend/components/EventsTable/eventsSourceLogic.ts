import { ErrorEventType } from 'lib/components/Errors/types'

import { EventsQuery } from '~/queries/schema/schema-general'

import { createDataSourceLogic } from '../DataSourceTable'

export interface EventsSourceProps {
    queryKey: string
    query: EventsQuery
}

type EventsQueryPerson = ErrorEventType['person'] & { distinct_id: string }

type EventsQueryRow = [
    event: Pick<ErrorEventType, 'uuid' | 'properties'>,
    timestamp: ErrorEventType['timestamp'],
    person: EventsQueryPerson,
]

function rowToRecord([event, timestamp, person]: EventsQueryRow): ErrorEventType {
    return {
        event: '$exception',
        uuid: event.uuid,
        timestamp,
        person,
        distinct_id: event.properties.distinct_id || person.distinct_id,
        properties: event.properties,
    }
}

export const eventsSourceLogic = createDataSourceLogic<EventsSourceProps, ErrorEventType, EventsQueryRow>(
    () => ['products', 'error_tracking', 'components', 'EventsTable', 'eventsSourceLogic'],
    rowToRecord
)
