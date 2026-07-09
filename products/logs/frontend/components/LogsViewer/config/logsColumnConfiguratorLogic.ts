import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { uuid } from 'lib/utils/dom'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

import { LogsColumnConfig, normalizeColumns } from './columns'
import type { logsColumnConfiguratorLogicType } from './logsColumnConfiguratorLogicType'

export interface LogsColumnConfiguratorLogicProps {
    id: string
}

/**
 * Draft-based editor state for the column configurator modal. Edits accumulate in a local
 * draft and only hit logsViewerConfigLogic (and thus the query) on an explicit apply — typing
 * in an expression input must never fire a logs query per keystroke.
 */
export const logsColumnConfiguratorLogic = kea<logsColumnConfiguratorLogicType>([
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'logsColumnConfiguratorLogic', key]),
    props({} as LogsColumnConfiguratorLogicProps),
    key((props) => props.id),
    connect(({ id }: LogsColumnConfiguratorLogicProps) => ({
        values: [logsViewerConfigLogic({ id }), ['columns']],
        actions: [logsViewerConfigLogic({ id }), ['setColumns']],
    })),

    actions({
        openConfigurator: true,
        closeConfigurator: true,
        setDraft: (draft: LogsColumnConfig[]) => ({ draft }),
        updateDraftColumn: (id: string, patch: Partial<Omit<LogsColumnConfig, 'id'>>) => ({ id, patch }),
        addDraftColumn: (column: Omit<LogsColumnConfig, 'id'>) => ({ column }),
        setEditingColumnId: (id: string | null) => ({ id }),
        removeDraftColumn: (id: string) => ({ id }),
        moveDraftColumn: (fromIndex: number, toIndex: number) => ({ fromIndex, toIndex }),
        applyDraft: true,
    }),

    reducers({
        isOpen: [
            false,
            {
                openConfigurator: () => true,
                closeConfigurator: () => false,
            },
        ],
        // The column being inline-edited in the visible list (custom columns only)
        editingColumnId: [
            null as string | null,
            {
                setEditingColumnId: (_, { id }) => id,
                openConfigurator: () => null,
                closeConfigurator: () => null,
                removeDraftColumn: () => null,
            },
        ],
        draft: [
            [] as LogsColumnConfig[],
            {
                setDraft: (_, { draft }) => normalizeColumns(draft),
                updateDraftColumn: (state, { id, patch }) =>
                    state.map((column) => (column.id === id ? { ...column, ...patch } : column)),
                addDraftColumn: (state, { column }) => normalizeColumns([...state, { ...column, id: uuid() }]),
                removeDraftColumn: (state, { id }) => state.filter((column) => column.id !== id),
                moveDraftColumn: (state, { fromIndex, toIndex }) => {
                    if (fromIndex === toIndex || !state[fromIndex] || toIndex < 0 || toIndex >= state.length) {
                        return state
                    }
                    const next = [...state]
                    const [moved] = next.splice(fromIndex, 1)
                    next.splice(toIndex, 0, moved)
                    return normalizeColumns(next)
                },
            },
        ],
    }),

    selectors({
        draftErrors: [
            (s) => [s.draft],
            (draft: LogsColumnConfig[]): string | null => {
                if (draft.length === 0) {
                    return 'At least one column is required'
                }
                if (draft.some((column) => column.type === 'custom' && !column.expression?.trim())) {
                    return 'Custom columns need an expression'
                }
                return null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openConfigurator: () => {
            actions.setDraft(values.columns)
        },
        applyDraft: () => {
            if (!values.draftErrors) {
                actions.setColumns(values.draft)
                actions.closeConfigurator()
            }
        },
    })),
])
