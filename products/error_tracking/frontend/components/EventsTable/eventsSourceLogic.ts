import { ErrorEventType } from 'lib/components/Errors/types'

import { EventsQuery } from '~/queries/schema/schema-general'

import { DataSourceLogicProps, createDataSourceLogic } from '../DataSourceTable'

export interface EventsSourceProps {
    queryKey: string
    query: EventsQuery
}

function rowToRecord(row: any): ErrorEventType {
    return {
        uuid: row[0].uuid,
        timestamp: row[1],
        person: row[2],
        properties: row[0].properties,
    }
}

export const eventsSourceLogic = createDataSourceLogic<DataSourceLogicProps<EventsQuery>, ErrorEventType>(
    () => ['products', 'error_tracking', 'components', 'EventsTable', 'eventsSourceLogic'],
    rowToRecord
)
