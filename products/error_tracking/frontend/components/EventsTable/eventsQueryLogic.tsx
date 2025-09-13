import { LogicWrapper, connect, kea, key, path, props, selectors } from 'kea'

import { uuid } from 'lib/utils'

import { ErrorTrackingRelationalIssue, EventsQuery } from '~/queries/schema/schema-general'

import { errorTrackingIssueEventsQuery } from '../../queries'
import { DataQueryLogic } from '../DataSourceTable'
import { issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import type { eventsQueryLogicType } from './eventsQueryLogicType'

export interface EventDataLogicProps {
    issueId: ErrorTrackingRelationalIssue['id']
}

export const eventsQueryLogic: LogicWrapper<DataQueryLogic<EventsQuery>> = kea<eventsQueryLogicType>([
    path((key) => ['products', 'error_tracking', 'components', 'EventsTable', 'eventsQueryLogic', key]),
    props({} as EventDataLogicProps),
    key((props) => props.issueId),

    connect(() => {
        return {
            values: [issueFiltersLogic, ['filterTestAccounts', 'searchQuery', 'filterGroup', 'dateRange']],
        }
    }),

    selectors({
        query: [
            (s) => [(_, props) => props.issueId, s.filterTestAccounts, s.searchQuery, s.filterGroup, s.dateRange],
            (issueId, filterTestAccounts, searchQuery, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    issueId,
                    filterTestAccounts,
                    filterGroup,
                    searchQuery,
                    dateRange,
                    columns: ['*', 'timestamp', 'person'],
                }),
        ],
        queryKey: [
            (s) => [s.query],
            () => {
                return uuid()
            },
        ],
    }),
])
