import { actions, defaults, kea, key, path, props, propsChanged, reducers } from 'kea'
import { forms } from 'kea-forms'
import 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import '~/lib/api'
import api from '~/lib/api'
import { DatasetItem } from '~/types'

import type { datasetItemModalLogicType } from './datasetItemModalLogicType'
import { EMPTY_JSON, corseJsonToObject, isStringJsonObject, prettifyJson } from './utils'

export type TraceMetadata = Required<Pick<DatasetItem, 'ref_trace_id' | 'ref_span_id' | 'ref_trace_timestamp'>>

export interface DatasetItemModalLogicProps {
    datasetId: string
    datasetItem?: DatasetItem | null
    traceMetadata?: TraceMetadata
    /**
     * @param action - Whether the item was created, updated, or no action was taken.
     */
    closeModal: (refetchDatasetItems?: boolean) => void
    isModalOpen: boolean
}

export enum DatasetTab {
    Items = 'items',
    Metadata = 'metadata',
}

export interface DatasetItemFormValues {
    input: string | null
    output: string | null
    metadata: string | null
}

export const DATASET_ITEMS_PER_PAGE = 50

const FORM_DEFAULT_VALUE: DatasetItemFormValues = {
    input: EMPTY_JSON,
    output: EMPTY_JSON,
    metadata: EMPTY_JSON,
}

export const datasetItemModalLogic = kea<datasetItemModalLogicType>([
    path(['scenes', 'llm-analytics', 'datasetItemModalLogic']),

    props({ datasetId: '', datasetItem: null, closeModal: () => {} } as DatasetItemModalLogicProps),

    key(({ datasetId, datasetItem }) => `dataset-item-${datasetId}-${datasetItem?.id || 'new'}`),

    actions({
        setShouldCloseModal: (shouldCloseModal: boolean) => ({ shouldCloseModal }),
        setRefetchDatasetItems: (refetchDatasetItems: boolean) => ({ refetchDatasetItems }),
    }),

    reducers(() => ({
        shouldCloseModal: [
            true as boolean,
            {
                setShouldCloseModal: (_, { shouldCloseModal }) => shouldCloseModal,
            },
        ],

        refetchDatasetItems: [
            false as boolean,
            {
                setRefetchDatasetItems: (_, { refetchDatasetItems }) => refetchDatasetItems,
            },
        ],
    })),

    forms(({ props, actions, values }) => ({
        datasetItemForm: {
            defaults: FORM_DEFAULT_VALUE as DatasetItemFormValues,

            errors: ({ input, output, metadata }) => ({
                input: !isStringJsonObject(input) ? 'Input must contain a valid JSON object' : undefined,
                output: !isStringJsonObject(output) ? 'Output must contain a valid JSON object' : undefined,
                metadata: !isStringJsonObject(metadata) ? 'Metadata must contain a valid JSON object' : undefined,
            }),

            submit: async (formValues) => {
                try {
                    if (!props.datasetItem) {
                        await api.datasetItems.create({
                            dataset: props.datasetId,
                            input: corseJsonToObject(formValues.input),
                            output: corseJsonToObject(formValues.output),
                            metadata: corseJsonToObject(formValues.metadata),
                        })
                        lemonToast.success('Dataset item created successfully')
                        if (values.shouldCloseModal) {
                            props.closeModal(true)
                        } else {
                            actions.setRefetchDatasetItems(true)
                        }
                        actions.setShouldCloseModal(true)
                    } else {
                        const updatedItem = await api.datasetItems.update(props.datasetItem.id, {
                            input: corseJsonToObject(formValues.input),
                            output: corseJsonToObject(formValues.output),
                            metadata: corseJsonToObject(formValues.metadata),
                        })
                        lemonToast.success('Dataset item updated successfully')
                        props.closeModal(true)
                        actions.setDatasetItemFormValues(getDatasetItemFormDefaults(updatedItem))
                    }
                } catch (error) {
                    console.error(error)
                    lemonToast.error('Failed to save a dataset item.')
                }
            },
        },
    })),

    defaults(({ props }): { datasetItemForm: DatasetItemFormValues } => ({
        datasetItemForm: props.datasetItem ? getDatasetItemFormDefaults(props.datasetItem) : FORM_DEFAULT_VALUE,
    })),

    propsChanged(({ props, actions }) => {
        if (!props.datasetItem && props.isModalOpen) {
            actions.resetDatasetItemForm()
        }

        if (props.isModalOpen) {
            actions.setRefetchDatasetItems(false)
        }
    }),
])

export function getDatasetItemFormDefaults(datasetItem: DatasetItem): DatasetItemFormValues {
    return {
        input: prettifyJson(datasetItem.input) || EMPTY_JSON,
        output: prettifyJson(datasetItem.output) || EMPTY_JSON,
        metadata: prettifyJson(datasetItem.metadata) || EMPTY_JSON,
    }
}
