import { KeyType, LogicWrapper, connect, kea, key, path, props, selectors } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { DataNode, DataTableNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { DataSourceLogic, DataSourceLogicProps } from './types'

// Alias kea function to prevent kea from generating types
const buildKea = kea

function defaultCreateKey<Props extends DataSourceLogicProps<DataNode>>({ queryKey }: Props): string {
    return queryKey
}

type DataSourceResponse<Row> = {
    results: Row[]
}

function hasResults<Row>(response: unknown): response is DataSourceResponse<Row> {
    return (
        typeof response === 'object' &&
        response !== null &&
        Array.isArray((response as DataSourceResponse<Row>).results)
    )
}

export function createDataSourceLogic<Props extends DataSourceLogicProps<DataNode>, T, Row = unknown[]>(
    createPath: (key: KeyType) => KeyType[],
    createRecord: (row: Row) => T,
    createKey: (props: Props) => KeyType = defaultCreateKey
): LogicWrapper<DataSourceLogic<T>> {
    return buildKea<DataSourceLogic<T>>([
        path(createPath),
        props({} as Props),
        key(createKey),
        connect((props: Props) => {
            const sourceKey = createKey(props)
            const dataKey = `DataNode.${sourceKey}`
            const insightProps: InsightLogicProps<DataTableNode> = {
                dashboardItemId: `new-AdHoc.${dataKey}`,
                dataNodeCollectionId: dataKey,
            }
            const vizKey = insightVizDataNodeKey(insightProps)
            const dataLogic = dataNodeLogic({
                key: vizKey,
                query: props.query,
                autoLoad: true,
            })
            return {
                values: [dataLogic, ['response', 'responseLoading', 'canLoadNextData']],
                actions: [dataLogic, ['loadData', 'loadNextData']],
            }
        }),

        selectors({
            items: [
                (s) => [s.response],
                (response: unknown) => {
                    if (hasResults<Row>(response)) {
                        return response.results.map(createRecord)
                    }
                    return []
                },
            ],
            itemsLoading: [(s) => [s.responseLoading], (loading: boolean) => loading],
        }),
    ])
}
