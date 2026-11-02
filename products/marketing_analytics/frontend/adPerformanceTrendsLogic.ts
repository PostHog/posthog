import { LogicWrapper, MakeLogicType, connect, kea, key, path, props, propsChanged, selectors } from 'kea'

import type { validColumnsForTiles } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { DataNodeLogicProps, dataNodeLogic, dataNodeLogicType } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { AdPerformanceSparkline, adPerformanceSparklines } from './adPerformanceMetrics'

export interface AdPerformanceTrendsLogicProps {
    query: TrendsQuery
    queryKey: string
    dataNodeCollectionId: string
}

function dataProps(props: AdPerformanceTrendsLogicProps): DataNodeLogicProps {
    return {
        key: props.queryKey,
        query: props.query,
        doNotLoad: !props.query.series.length,
        dataNodeCollectionId: props.dataNodeCollectionId,
    }
}

export interface adPerformanceTrendsLogicValues extends Pick<
    dataNodeLogicType['values'],
    'response' | 'responseLoading' | 'responseError'
> {
    sparklines: Partial<Record<validColumnsForTiles, AdPerformanceSparkline>>
}

export type adPerformanceTrendsLogicType = MakeLogicType<
    adPerformanceTrendsLogicValues,
    {},
    AdPerformanceTrendsLogicProps
>

export const adPerformanceTrendsLogic: LogicWrapper<adPerformanceTrendsLogicType> = kea<adPerformanceTrendsLogicType>([
    props({} as AdPerformanceTrendsLogicProps),
    key(({ queryKey }) => queryKey),
    path((key) => ['products', 'marketingAnalytics', 'adPerformanceTrendsLogic', key]),
    connect((props: AdPerformanceTrendsLogicProps) => ({
        values: [dataNodeLogic(dataProps(props)), ['response', 'responseLoading', 'responseError']],
    })),
    selectors({
        sparklines: [
            (s, p) => [s.response, s.responseLoading, s.responseError, p.query],
            (
                response,
                loading,
                error,
                query: TrendsQuery
            ): Partial<Record<validColumnsForTiles, AdPerformanceSparkline>> =>
                loading || error
                    ? {}
                    : adPerformanceSparklines(
                          query,
                          ((response as TrendsQueryResponse | null)?.results ?? []) as TrendResult[]
                      ),
        ],
    }),
    propsChanged(({ props }, oldProps) => {
        if (JSON.stringify(props.query) !== JSON.stringify(oldProps.query)) {
            const logic = dataNodeLogic.findMounted({ key: props.queryKey })
            logic?.actions.abortAnyRunningQuery()
            logic?.actions.clearResponse()
            dataNodeLogic(dataProps(props))
        }
    }),
])
