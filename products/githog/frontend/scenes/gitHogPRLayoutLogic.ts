import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRLayoutLogicType } from './gitHogPRLayoutLogicType'

export type GitHogWidgetType =
    | 'conversation'
    | 'stats'
    | 'files'
    | 'reviewers'
    | 'agent'
    | 'dataFlow'
    | 'riskScore'
    | 'impact'

export interface GitHogLayoutItem {
    i: GitHogWidgetType | string
    x: number
    y: number
    w: number
    h: number
}

export interface GitHogPRLayoutResponse {
    items: GitHogLayoutItem[]
    exists: boolean
}

// Default layout on the 12-col grid used by the PR workspace. Tuned so the most
// important signals (risk + flow) land above the fold on a typical screen.
export const DEFAULT_LAYOUT: GitHogLayoutItem[] = [
    { i: 'riskScore', x: 8, y: 0, w: 4, h: 5 },
    { i: 'dataFlow', x: 0, y: 0, w: 8, h: 7 },
    { i: 'stats', x: 8, y: 5, w: 4, h: 3 },
    { i: 'impact', x: 0, y: 7, w: 8, h: 8 },
    { i: 'files', x: 8, y: 8, w: 4, h: 5 },
]

const SAVE_DEBOUNCE_MS = 500

// Layouts are stored per-user only — the same arrangement applies to every PR
// across every repository and team. The logic is a singleton (no key/props).
export const gitHogPRLayoutLogic = kea<gitHogPRLayoutLogicType>([
    path(['scenes', 'githog', 'gitHogPRLayoutLogic']),
    actions({
        setLayout: (items: GitHogLayoutItem[]) => ({ items }),
        addWidget: (widget: GitHogWidgetType) => ({ widget }),
        removeWidget: (widget: GitHogWidgetType) => ({ widget }),
        persistLayout: true,
    }),
    reducers({
        layoutItems: [
            DEFAULT_LAYOUT as GitHogLayoutItem[],
            {
                setLayout: (_, { items }) => items,
                addWidget: (state, { widget }) => {
                    if (state.some((it) => it.i === widget)) {
                        return state
                    }
                    // Place the new widget on a new row at the bottom, full width by default.
                    const maxY = state.reduce((acc, it) => Math.max(acc, it.y + it.h), 0)
                    return [...state, { i: widget, x: 0, y: maxY, w: 12, h: 4 }]
                },
                removeWidget: (state, { widget }) => state.filter((it) => it.i !== widget),
                loadLayoutSuccess: (state, { layout }) => {
                    if (layout && layout.exists && layout.items.length > 0) {
                        return layout.items
                    }
                    return state
                },
            },
        ],
    }),
    loaders(() => ({
        layout: [
            null as GitHogPRLayoutResponse | null,
            {
                loadLayout: async () => {
                    return await api.get<GitHogPRLayoutResponse>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_layout/`
                    )
                },
            },
        ],
    })),
    selectors({
        widgets: [(s) => [s.layoutItems], (items): GitHogWidgetType[] => items.map((it) => it.i as GitHogWidgetType)],
    }),
    listeners(({ values, actions }) => ({
        setLayout: () => actions.persistLayout(),
        addWidget: () => actions.persistLayout(),
        removeWidget: () => actions.persistLayout(),
        persistLayout: async (_, breakpoint) => {
            // Debounce: drag/resize fires many onLayoutChange events. The kea
            // breakpoint helper cancels this listener call if another fires
            // before the timeout elapses, so only the trailing change is saved.
            await breakpoint(SAVE_DEBOUNCE_MS)
            await api.put(`api/environments/${getCurrentTeamId()}/githog/pull_request_layout/`, {
                items: values.layoutItems,
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLayout()
    }),
])
