import { LogicWrapper, MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

interface NotebookCohortFilterProps {
    shortId: string
}

type PreviewCohort = { id: number; name: string } | null

export interface notebookCohortFilterLogicValues {
    previewCohort: PreviewCohort
}

export interface notebookCohortFilterLogicActions {
    setPreviewCohort: (cohort: PreviewCohort) => { cohort: PreviewCohort }
}

export type notebookCohortFilterLogicType = MakeLogicType<
    notebookCohortFilterLogicValues,
    notebookCohortFilterLogicActions,
    NotebookCohortFilterProps
>

export const notebookCohortFilterLogic: LogicWrapper<notebookCohortFilterLogicType> =
    kea<notebookCohortFilterLogicType>([
        path(['products', 'notebooks', 'frontend', 'notebookCohortFilterLogic']),
        props({} as NotebookCohortFilterProps),
        key((props) => props.shortId),
        actions({ setPreviewCohort: (cohort: PreviewCohort) => ({ cohort }) }),
        reducers({ previewCohort: [null as PreviewCohort, { setPreviewCohort: (_, { cohort }) => cohort }] }),
        listeners(({ props }) => ({
            setPreviewCohort: ({ cohort }) => {
                posthog.capture('notebook cohort preview changed', { notebook_id: props.shortId, active: !!cohort })
            },
        })),
    ])
