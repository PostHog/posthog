import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { gitHogPRLayoutLogicType } from './gitHogPRLayoutLogicType'

export type GitHogWidgetType = 'conversation' | 'stats' | 'files' | 'reviewers' | 'agent' | 'dataFlow' | 'riskScore'

export interface GitHogLayoutItem {
    i: GitHogWidgetType | string
    x: number
    y: number
    w: number
    h: number
}

export interface GitHogPRLayoutLogicProps {
    owner: string
    name: string
    number: number
}

export interface GitHogPRLayoutResponse {
    repository: string
    pr_number: number
    items: GitHogLayoutItem[]
    exists: boolean
}

// Default layout on the 12-col grid used by the PR workspace. Tuned so the most
// important signals (risk + flow) land above the fold on a typical screen.
export const DEFAULT_LAYOUT: GitHogLayoutItem[] = [
    { i: 'riskScore', x: 8, y: 0, w: 4, h: 5 },
    { i: 'dataFlow', x: 0, y: 0, w: 8, h: 7 },
    { i: 'stats', x: 8, y: 5, w: 4, h: 3 },
    { i: 'files', x: 0, y: 7, w: 8, h: 5 },
]

const SAVE_DEBOUNCE_MS = 500

export const gitHogPRLayoutLogic = kea<gitHogPRLayoutLogicType>([
    props({} as GitHogPRLayoutLogicProps),
    key((p) => `${p.owner}/${p.name}#${p.number}`),
    path((k) => ['scenes', 'githog', 'gitHogPRLayoutLogic', k]),
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
    loaders(({ props }) => ({
        layout: [
            null as GitHogPRLayoutResponse | null,
            {
                loadLayout: async () => {
                    const repository = `${props.owner}/${props.name}`
                    const params = new URLSearchParams({ repository, number: String(props.number) })
                    return await api.get<GitHogPRLayoutResponse>(
                        `api/environments/${getCurrentTeamId()}/githog/pull_request_layout/?${params.toString()}`
                    )
                },
            },
        ],
    })),
    selectors({
        widgets: [(s) => [s.layoutItems], (items): GitHogWidgetType[] => items.map((it) => it.i as GitHogWidgetType)],
    }),
    listeners(({ props, values, actions }) => ({
        setLayout: () => actions.persistLayout(),
        addWidget: () => actions.persistLayout(),
        removeWidget: () => actions.persistLayout(),
        persistLayout: async (_, breakpoint) => {
            // Debounce: drag/resize fires many onLayoutChange events. The kea
            // breakpoint helper cancels this listener call if another fires
            // before the timeout elapses, so only the trailing change is saved.
            await breakpoint(SAVE_DEBOUNCE_MS)
            const repository = `${props.owner}/${props.name}`
            await api.put(`api/environments/${getCurrentTeamId()}/githog/pull_request_layout/`, {
                repository,
                number: props.number,
                items: values.layoutItems,
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLayout()
    }),
])
