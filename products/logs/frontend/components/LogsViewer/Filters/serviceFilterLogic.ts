import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'

import type { serviceFilterLogicType } from './serviceFilterLogicType'

export interface ServiceFilterLogicProps {
    dateRange?: DateRange
}

export const serviceFilterLogic = kea<serviceFilterLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'Filters', 'serviceFilterLogic']),
    props({} as ServiceFilterLogicProps),
    key((props) => `${props.dateRange?.date_from ?? 'all'}_${props.dateRange?.date_to ?? 'all'}`),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        setSearch: (search: string) => ({ search }),
    }),

    reducers({
        search: ['' as string, { setSearch: (_, { search }) => search }],
    }),

    loaders(({ values, props: logicProps }) => ({
        allServiceNames: [
            [] as string[],
            {
                loadServiceNames: async () => {
                    const url = combineUrl(`api/environments/${values.currentTeamId}/logs/values`, {
                        key: 'service.name',
                        attribute_type: 'resource',
                        value: values.search,
                        limit: 1000,
                        ...(logicProps.dateRange ? { dateRange: JSON.stringify(logicProps.dateRange) } : {}),
                    }).url
                    const response = await api.get(url)
                    return ((response.results ?? []) as { name: string }[]).map((r) => r.name)
                },
            },
        ],
    })),

    selectors({
        serviceNames: [(s) => [s.allServiceNames], (allServiceNames): string[] => allServiceNames],
    }),

    listeners(({ actions }) => ({
        setSearch: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadServiceNames()
        },
    })),

    propsChanged(({ actions, props: newProps }, oldProps) => {
        if (
            newProps.dateRange?.date_from !== oldProps?.dateRange?.date_from ||
            newProps.dateRange?.date_to !== oldProps?.dateRange?.date_to
        ) {
            actions.loadServiceNames()
        }
    }),

    afterMount(({ actions }) => {
        actions.loadServiceNames()
    }),
])
