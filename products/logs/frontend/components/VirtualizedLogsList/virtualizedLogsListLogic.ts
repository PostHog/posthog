import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import type { virtualizedLogsListLogicType } from './virtualizedLogsListLogicType'

export interface VirtualizedLogsListLogicProps {
    tabId: string
    scrollThreshold?: number
}

const DEFAULT_SCROLL_THRESHOLD = 100

export const virtualizedLogsListLogic = kea<virtualizedLogsListLogicType>([
    props({ scrollThreshold: DEFAULT_SCROLL_THRESHOLD } as VirtualizedLogsListLogicProps),
    key((props) => props.tabId),
    path((tabId) => [
        'products',
        'logs',
        'frontend',
        'components',
        'VirtualizedLogsList',
        'virtualizedLogsListLogic',
        tabId,
    ]),

    actions({
        setContainerWidth: (width: number) => ({ width }),
        setCellScrollLeft: (cellKey: string, scrollLeft: number) => ({ cellKey, scrollLeft }),
    }),

    reducers({
        containerWidth: [
            0,
            {
                setContainerWidth: (_, { width }) => width,
            },
        ],
        cellScrollLefts: [
            {} as Record<string, number>,
            { persist: true },
            {
                setCellScrollLeft: (state, { cellKey, scrollLeft }) => ({
                    ...state,
                    [cellKey]: scrollLeft,
                }),
            },
        ],
    }),

    selectors({
        shouldLoadMore: [
            () => [(_, props) => props.scrollThreshold ?? DEFAULT_SCROLL_THRESHOLD],
            (scrollThreshold) =>
                (stopIndex: number, dataSourceLength: number, hasMore: boolean, isLoading: boolean): boolean => {
                    if (!hasMore || isLoading) {
                        return false
                    }
                    return stopIndex >= dataSourceLength - scrollThreshold
                },
        ],
    }),
])
