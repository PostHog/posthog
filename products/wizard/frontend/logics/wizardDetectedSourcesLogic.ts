import { LogicWrapper, MakeLogicType, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { projectLogic } from 'scenes/projectLogic'

import { wizardScansDetectedSourcesRetrieve } from '../generated/api'
import type { WizardDetectedWarehouseSourceApi } from '../generated/api.schemas'

export interface wizardDetectedSourcesLogicValues {
    currentProjectId: number | null
    detectedSources: WizardDetectedWarehouseSourceApi[] | null
    detectedSourcesLoading: boolean
    detectedSourceTypes: ReadonlySet<string>
}

export interface wizardDetectedSourcesLogicActions {
    loadDetectedSources: () => void
    loadDetectedSourcesSuccess: (detectedSources: WizardDetectedWarehouseSourceApi[] | null) => {
        detectedSources: WizardDetectedWarehouseSourceApi[] | null
    }
    loadDetectedSourcesFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
}

export type wizardDetectedSourcesLogicType = MakeLogicType<
    wizardDetectedSourcesLogicValues,
    wizardDetectedSourcesLogicActions
>

/** The data warehouse sources the setup agent found in the current project's codebases. */
export const wizardDetectedSourcesLogic: LogicWrapper<wizardDetectedSourcesLogicType> =
    kea<wizardDetectedSourcesLogicType>([
        path(['products', 'wizard', 'wizardDetectedSourcesLogic']),
        connect(() => ({
            values: [projectLogic, ['currentProjectId']],
        })),
        loaders(({ values }) => ({
            detectedSources: [
                null as WizardDetectedWarehouseSourceApi[] | null,
                {
                    loadDetectedSources: async () =>
                        values.currentProjectId === null
                            ? null
                            : await wizardScansDetectedSourcesRetrieve(String(values.currentProjectId)),
                },
            ],
        })),
        selectors({
            detectedSourceTypes: [
                (s) => [s.detectedSources],
                (sources: WizardDetectedWarehouseSourceApi[] | null): ReadonlySet<string> =>
                    new Set((sources ?? []).map((source) => source.warehouse_source_type)),
            ],
        }),
        afterMount(({ actions }) => {
            actions.loadDetectedSources()
        }),
    ])
