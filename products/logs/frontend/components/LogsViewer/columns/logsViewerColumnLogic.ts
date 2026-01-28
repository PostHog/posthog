import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    DEFAULT_CONFIGURABLE_COLUMNS_BY_ID,
    FIXED_COLUMNS_BY_ID,
} from 'products/logs/frontend/components/LogsViewer/columns/constants'
import { DEFAULT_ATTRIBUTE_COLUMN_WIDTH } from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'

import type { ParsedLogMessage } from '../../../types'
import type { logsViewerColumnLogicType } from './logsViewerColumnLogicType'
import type { Column, ConfigurableColumn } from './types'

export interface LogsViewerColumnLogicProps {
    id: string
}

const getNextAvailableColumnOrderPosition = (columnsById: Record<string, ConfigurableColumn>): number => {
    const fixedMaxOrder = Math.max(...Object.values(FIXED_COLUMNS_BY_ID).map((c) => c.order ?? 0))
    const configurableOrders = Object.values(columnsById).map((c) => c.order ?? 0)
    const maxOrder = configurableOrders.length > 0 ? Math.max(fixedMaxOrder, ...configurableOrders) : fixedMaxOrder
    return maxOrder + 1
}

export const logsViewerColumnLogic = kea<logsViewerColumnLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'columns', 'logsViewerColumnLogic']),
    props({ id: 'default' } as LogsViewerColumnLogicProps),
    key((props) => props.id),

    actions({
        setConfigurableColumns: (columns: Record<string, ConfigurableColumn>) => ({ columns }),
        setColumnWidth: (columnId: string, width: number) => ({ columnId, width }),
        addAttributeColumn: (attributeKey: string) => ({ attributeKey }),
        toggleAttributeColumn: (attributeKey: string) => ({ attributeKey }),
        removeColumn: (columnId: string) => ({ columnId }),
        moveColumn: (columnId: string, direction: 'left' | 'right') => ({ columnId, direction }),
    }),

    reducers({
        configurableColumnsById: [
            DEFAULT_CONFIGURABLE_COLUMNS_BY_ID as Record<string, ConfigurableColumn>,
            { persist: true },
            {
                setConfigurableColumns: (_, { columns }) => columns,
                setColumnWidth: (state, { columnId, width }) =>
                    state[columnId] ? { ...state, [columnId]: { ...state[columnId], width } } : state,
                addAttributeColumn: (state, { attributeKey }) => {
                    const id = `attribute-${attributeKey}` as const
                    return {
                        ...state,
                        [id]: {
                            id,
                            type: 'attribute' as const,
                            order: getNextAvailableColumnOrderPosition(state),
                            label: attributeKey,
                            attributeKey,
                            width: DEFAULT_ATTRIBUTE_COLUMN_WIDTH,
                        },
                    }
                },
                removeColumn: (state, { columnId }) => {
                    const { [columnId]: _, ...rest } = state
                    return rest
                },
                moveColumn: (state, { columnId, direction }) => {
                    const column = state[columnId]
                    if (!column) {
                        return state
                    }

                    // Get all configurable columns sorted by order (excluding body which is always last)
                    const sortedColumns = Object.values(state)
                        .filter((c) => c.type !== 'body')
                        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

                    const currentIndex = sortedColumns.findIndex((c) => c.id === columnId)
                    const targetIndex = direction === 'left' ? currentIndex - 1 : currentIndex + 1

                    if (targetIndex < 0 || targetIndex >= sortedColumns.length) {
                        return state
                    }

                    const targetColumn = sortedColumns[targetIndex]
                    if (!targetColumn) {
                        return state
                    }

                    // Swap orders
                    return {
                        ...state,
                        [columnId]: { ...column, order: targetColumn.order },
                        [targetColumn.id]: { ...targetColumn, order: column.order },
                    }
                },
            },
        ],
    }),

    selectors({
        columnsById: [
            (s) => [s.configurableColumnsById],
            (configurableColumnsById): Record<string, Column> => ({
                ...FIXED_COLUMNS_BY_ID,
                ...configurableColumnsById,
            }),
        ],
        columns: [
            (s) => [s.columnsById],
            (columnsById: Record<string, Column>): Column[] =>
                Object.values(columnsById).sort((a: Column, b: Column) => {
                    // Body column always last
                    if (a.type === 'body') {
                        return 1
                    }
                    if (b.type === 'body') {
                        return -1
                    }
                    return (a.order ?? 0) - (b.order ?? 0)
                }),
        ],
        compiledPaths: [
            (s) => [s.columns],
            (columns): Map<string, string[]> => {
                const paths = new Map<string, string[]>()
                for (const col of columns) {
                    if (col.type === 'expression') {
                        paths.set(col.expression, col.expression.split('.'))
                    }
                }
                return paths
            },
        ],
        getColumnById: [
            (s) => [s.columnsById],
            (columnsById: Record<string, Column>) =>
                (columnId: string): Column | undefined => {
                    return columnsById[columnId]
                },
        ],
        isAttributeColumn: [
            (s) => [s.configurableColumnsById],
            (configurableColumnsById: Record<string, ConfigurableColumn>) =>
                (attributeKey: string): boolean => {
                    const id = `attribute-${attributeKey}`
                    const col = configurableColumnsById[id]
                    return col?.type === 'attribute'
                },
        ],
        sortedConfigurableColumns: [
            (s) => [s.configurableColumnsById],
            (configurableColumnsById: Record<string, ConfigurableColumn>): ConfigurableColumn[] =>
                Object.values(configurableColumnsById)
                    .filter((c) => c.type !== 'body')
                    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
        ],
        isFirstConfigurableColumn: [
            (s) => [s.sortedConfigurableColumns],
            (sortedColumns: ConfigurableColumn[]) =>
                (columnId: string): boolean => {
                    return sortedColumns.length > 0 && sortedColumns[0]?.id === columnId
                },
        ],
        isLastConfigurableColumn: [
            (s) => [s.sortedConfigurableColumns],
            (sortedColumns: ConfigurableColumn[]) =>
                (columnId: string): boolean => {
                    return sortedColumns.length > 0 && sortedColumns[sortedColumns.length - 1]?.id === columnId
                },
        ],
        evaluateExpression: [
            (s) => [s.compiledPaths],
            (compiledPaths) =>
                (log: ParsedLogMessage, expression: string): unknown => {
                    let path = compiledPaths.get(expression)
                    if (!path) {
                        path = expression.split('.')
                    }

                    let value: unknown = log
                    for (const key of path) {
                        if (value == null || typeof value !== 'object') {
                            return undefined
                        }
                        value = (value as Record<string, unknown>)[key]
                    }
                    return value
                },
        ],
    }),

    listeners(({ actions, values }) => ({
        toggleAttributeColumn: ({ attributeKey }) => {
            const columnId = `attribute-${attributeKey}`
            if (values.isAttributeColumn(attributeKey)) {
                actions.removeColumn(columnId)
            } else {
                actions.addAttributeColumn(attributeKey)
            }
        },
    })),
])
