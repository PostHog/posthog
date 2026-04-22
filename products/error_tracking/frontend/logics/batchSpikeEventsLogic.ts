import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'

import { DateRange } from '~/queries/schema/schema-general'

import { dateRangeToIsoBounds } from '../utils'
import type { batchSpikeEventsLogicType } from './batchSpikeEventsLogicType'

export const batchSpikeEventsLogic = kea<batchSpikeEventsLogicType>([
    path(['products', 'error_tracking', 'logics', 'batchSpikeEventsLogic']),

    actions({
        loadSpikeEventsForIssues: (issueIds: string[], dateRange?: DateRange) => ({ issueIds, dateRange }),
    }),

    loaders({
        rawSpikeEvents: [
            [] as ErrorTrackingSpikeEvent[],
            {
                loadSpikeEventsForIssues: async ({ issueIds, dateRange }, breakpoint) => {
                    if (issueIds.length === 0) {
                        return []
                    }
                    await breakpoint(100)
                    const { dateFrom, dateTo } = dateRangeToIsoBounds(dateRange)
                    const response = await api.errorTracking.getSpikeEvents({ issueIds, dateFrom, dateTo })
                    return response.results
                },
            },
        ],
    }),

    reducers({
        spikeEventsByIssueId: [
            {} as Record<string, ErrorTrackingSpikeEvent[]>,
            {
                loadSpikeEventsForIssues: () => ({}),
                loadSpikeEventsForIssuesSuccess: (_, { rawSpikeEvents }) => {
                    const grouped: Record<string, ErrorTrackingSpikeEvent[]> = {}
                    for (const event of rawSpikeEvents) {
                        const id = event.issue.id
                        if (!grouped[id]) {
                            grouped[id] = []
                        }
                        grouped[id].push(event)
                    }
                    return grouped
                },
            },
        ],
    }),
])
