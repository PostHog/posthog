import { KeyType, Logic } from 'kea'

import type { DataNode, RefreshType } from '~/queries/schema/schema-general'

export interface DataSourceLogic<T> extends Logic {
    values: {
        query: DataNode
        items: Array<T>
        itemsLoading: boolean
        canLoadNextData: boolean
    }
    actions: {
        setQuery: (query: DataNode) => void
        loadData: (refresh?: RefreshType) => void
        loadNextData: () => void
    }
}

export interface DataQueryLogic<Q extends DataNode> extends Logic {
    values: {
        query: Q
        queryKey: string
    }
    key: KeyType
}

export interface DataSourceLogicProps<Q> {
    query: Q
    queryKey: string
}
