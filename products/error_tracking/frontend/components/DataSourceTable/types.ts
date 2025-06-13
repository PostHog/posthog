import { KeyType, Logic } from 'kea'

import { DataNode } from '~/queries/schema/schema-general'

export interface DataSourceLogic<T> extends Logic {
    values: {
        query: DataNode
        items: Array<T>
        itemsLoading: boolean
        canLoadNextData: boolean
    }
    actions: {
        setQuery: (query: DataNode) => void
        loadData: () => void
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
