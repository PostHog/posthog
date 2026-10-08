import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'

import {
    DataNodeLogicProps,
    dataNodeLogic,
    dataNodeLogicType,
    dataNodeLogicActions,
} from '~/queries/nodes/DataNode/dataNodeLogic'

export interface SearchAndAiQueryLogicProps {
    dataNodeLogicProps: DataNodeLogicProps
    resultsKey?: string
}

export interface searchAndAiQueryLogicValues {
    response: dataNodeLogicType['values']['response']
    responseLoading: boolean
    dataQuery: dataNodeLogicType['values']['query']
    responseInput: string | null
    resultsKey: string | null
    lastResponse: dataNodeLogicType['values']['response']
    queryInput: string
    hasCurrentResponse: boolean
}

export interface searchAndAiQueryLogicActions {
    setResultsKey: (resultsKey: string | null) => { resultsKey: string | null }
    loadDataSuccess: dataNodeLogicActions['loadDataSuccess']
    loadNextDataSuccess: dataNodeLogicActions['loadNextDataSuccess']
    rememberResponse: (
        response: dataNodeLogicType['values']['response'],
        input: string
    ) => { response: dataNodeLogicType['values']['response']; input: string }
}

export type searchAndAiQueryLogicType = MakeLogicType<
    searchAndAiQueryLogicValues,
    searchAndAiQueryLogicActions,
    SearchAndAiQueryLogicProps
>

export const searchAndAiQueryLogic: LogicWrapper<searchAndAiQueryLogicType> = kea<searchAndAiQueryLogicType>([
    props({} as SearchAndAiQueryLogicProps),
    key(({ dataNodeLogicProps }) => dataNodeLogicProps.key),
    path((key) => ['products', 'web_analytics', 'searchAndAiQueryLogic', key]),
    connect(({ dataNodeLogicProps }: SearchAndAiQueryLogicProps) => ({
        values: [dataNodeLogic(dataNodeLogicProps), ['response', 'responseLoading', 'query as dataQuery']],
        actions: [dataNodeLogic(dataNodeLogicProps), ['loadDataSuccess', 'loadNextDataSuccess']],
    })),
    actions({
        setResultsKey: (resultsKey: string | null) => ({ resultsKey }),
        rememberResponse: (response: dataNodeLogicType['values']['response'], input: string) => ({ response, input }),
    }),
    reducers(({ props }) => ({
        resultsKey: [props.resultsKey ?? null, { setResultsKey: (_, { resultsKey }) => resultsKey }],
        responseInput: [null as string | null, { rememberResponse: (_, { input }) => input }],
        lastResponse: [
            null as dataNodeLogicType['values']['response'],
            {
                rememberResponse: (_, { response }) => response,
            },
        ],
    })),
    propsChanged(({ props, actions }, oldProps) => {
        if (props.resultsKey !== oldProps.resultsKey) {
            actions.setResultsKey(props.resultsKey ?? null)
        }
    }),
    selectors({
        queryInput: [
            (s) => [s.dataQuery, s.resultsKey],
            (query, resultsKey): string => resultsKey ?? JSON.stringify(query),
        ],
        hasCurrentResponse: [
            (s) => [s.queryInput, s.responseInput, s.lastResponse],
            (queryInput, responseInput, response): boolean => !!response && queryInput === responseInput,
        ],
    }),
    listeners(({ values, actions }) => ({
        loadDataSuccess: ({ response }) => actions.rememberResponse(response ?? null, values.queryInput),
        loadNextDataSuccess: ({ response }) => actions.rememberResponse(response ?? null, values.queryInput),
    })),
    afterMount(({ values, actions }) => {
        if (values.response && !values.responseLoading) {
            actions.rememberResponse(values.response, values.queryInput)
        }
    }),
])
