import { actions, connect, kea, key, listeners, loaders, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { ApiRequest } from 'lib/api'
import { objectClean } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { _LogAttributeEntryApi } from 'products/logs/frontend/generated/api.schemas'

import { logsViewerFiltersLogic } from '../Filters/logsViewerFiltersLogic'

export interface LogsColumnsModalLogicProps {
    viewerId: string
}

// Intentionally untyped (no *LogicType.ts): `*Type.ts` is gitignored and phrocs `typegen:watch` must
// generate files locally — a new keyed logic would otherwise brick the bundle until typegen succeeds.
export const logsColumnsModalLogic = kea([
    props({} as LogsColumnsModalLogicProps),
    key((props) => props.viewerId),
    path((key) => [
        'products',
        'logs',
        'frontend',
        'components',
        'LogsViewer',
        'LogsColumnsModal',
        'logsColumnsModalLogic',
        key,
    ]),

    connect((props: LogsColumnsModalLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            logsViewerFiltersLogic({ id: props.viewerId }),
            ['filters', 'utcDateRange'],
        ],
    })),

    actions({
        openModal: true,
        closeModal: true,
        setSearchQuery: (query: string) => ({ query }),
        setAttributeTypeTab: (tab: 'log' | 'resource') => ({ tab }),
        loadAttributeKeySuggestions: true,
    }),

    reducers({
        modalVisible: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
                openModal: () => '',
            },
        ],
        attributeTypeTab: [
            'log' as 'log' | 'resource',
            {
                setAttributeTypeTab: (_, { tab }) => tab,
                openModal: () => 'log',
            },
        ],
    }),

    loaders(({ values }) => ({
        attributeKeySuggestions: [
            [] as _LogAttributeEntryApi[],
            {
                loadAttributeKeySuggestions: async (_, breakpoint) => {
                    await breakpoint(280)
                    if (!values.modalVisible) {
                        return []
                    }
                    const teamId = values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const { filters, utcDateRange, searchQuery, attributeTypeTab } = values
                    const data = await new ApiRequest()
                        .logsAttributes(teamId)
                        .withQueryString(
                            objectClean({
                                dateRange: utcDateRange,
                                serviceNames: filters.serviceNames,
                                filterGroup: filters.filterGroup,
                                attribute_type: attributeTypeTab,
                                search: searchQuery.trim() || undefined,
                                limit: 50,
                                offset: 0,
                            })
                        )
                        .get()
                    return (data.results ?? []) as _LogAttributeEntryApi[]
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        openModal: () => {
            posthog.capture('logs columns modal opened')
            actions.loadAttributeKeySuggestions()
        },
        setSearchQuery: () => {
            actions.loadAttributeKeySuggestions()
        },
        setAttributeTypeTab: () => {
            actions.loadAttributeKeySuggestions()
        },
    })),
])
