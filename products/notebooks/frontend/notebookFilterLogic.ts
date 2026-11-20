import { LogicWrapper, MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import type { NotebookFilters } from './notebookFilters'

interface NotebookFilterProps {
    shortId: string
}

type NotebookFilterLogic = MakeLogicType<
    { filters: NotebookFilters | null },
    { setFilters: (filters: NotebookFilters | null) => { filters: NotebookFilters | null } },
    NotebookFilterProps
>

export const notebookFilterLogic: LogicWrapper<NotebookFilterLogic> = kea<NotebookFilterLogic>([
    path(['products', 'notebooks', 'frontend', 'notebookFilterLogic']),
    props({} as NotebookFilterProps),
    key((props) => props.shortId),
    actions({ setFilters: (filters: NotebookFilters | null) => ({ filters }) }),
    reducers({
        filters: [
            null as NotebookFilters | null,
            { setFilters: (_, { filters }) => (filters?.dateRange || filters?.properties.length ? filters : null) },
        ],
    }),
    listeners(({ props, values }) => ({
        setFilters: () => {
            posthog.capture('notebook filters changed', {
                notebook_id: props.shortId,
                property_count: values.filters?.properties.length ?? 0,
                has_date_range: !!values.filters?.dateRange,
            })
        },
    })),
])
