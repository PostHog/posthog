import { actions, kea, path, props, reducers, selectors } from 'kea'

import type { virtualizedLogsListLogicType } from './virtualizedLogsListLogicType'

export interface VirtualizedLogsListLogicProps {
    scrollThreshold: number
}

const DEFAULT_SCROLL_THRESHOLD = 100

export const virtualizedLogsListLogic = kea<virtualizedLogsListLogicType>([
    props({ scrollThreshold: DEFAULT_SCROLL_THRESHOLD } as VirtualizedLogsListLogicProps),
    path(['products', 'logs', 'frontend', 'components', 'VirtualizedLogsList', 'virtualizedLogsListLogic']),

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
            (_, p) => [p.scrollThreshold],
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
