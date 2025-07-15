import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import type { linkMetricSparklineLogicType } from './linkMetricSparklineLogicType'

export type Props = {
    id: string
}

export type SparklineDataResponse = {
    data: number[]
    labels: string[]
}

export const linkMetricSparklineLogic = kea<linkMetricSparklineLogicType>([
    props({} as Props),
    key(({ id }: Props) => id),
    path(['scenes', 'links', 'linkMetricSparklineLogic', 'id']),
    loaders({
        sparklineData: [
            null as SparklineDataResponse | null,
            {
                loadSparklineData: async () => {
                    const query: TrendsQuery = setLatestVersionsOnQuery({
                        kind: NodeKind.TrendsQuery,
                        filterTestAccounts: false,
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBar,
                        },

                        // TODO: Update to $linkclick event once ready
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: '$pageview',
                                name: '$pageview',
                            },
                        ],
                    })
                    const response = await api.query(query)
                    return response.results[0] as SparklineDataResponse
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSparklineData()
    }),
])
