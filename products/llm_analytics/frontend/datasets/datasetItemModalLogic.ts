import { actions, defaults, kea, key, path, props, propsChanged, reducers } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from '~/lib/api'
import { DatasetItem } from '~/types'

import type { datasetItemModalLogicType } from './datasetItemModalLogicType'
import { EMPTY_JSON, coerceJsonToObject, isStringJsonObject, prettifyJson } from './utils'

export type TraceMetadata = Required<Pick<DatasetItem, 'ref_trace_id' | 'ref_source_id' | 'ref_timestamp'>>

export interface DatasetItemModalLogicProps {
    datasetId: string
    partialDatasetItem?: Partial<DatasetItem> | null
    traceMetadata?: TraceMetadata
    /**
     * @param refetchDatasetItems - Whether the action was taken.
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

    props({ datasetId: '', partialDatasetItem: null, closeModal: () => {} } as DatasetItemModalLogicProps),

    key(({ datasetId, partialDatasetItem }) => `dataset-item-${datasetId}-${partialDatasetItem?.id || 'new'}`),

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
                    if (!props.partialDatasetItem?.id) {
                        await api.datasetItems.create({
                            ...props.partialDatasetItem,
                            dataset: props.datasetId,
                            input: coerceJsonToObject(formValues.input),
                            output: coerceJsonToObject(formValues.output),
                            metadata: coerceJsonToObject(formValues.metadata),
                        })
                        lemonToast.success('Dataset item created successfully')
                        if (values.shouldCloseModal) {
                            props.closeModal(true)
                        } else {
                            actions.setRefetchDatasetItems(true)
                            // In case of "save and add another", we want to reset the form values.
                            actions.setDatasetItemFormValues(FORM_DEFAULT_VALUE)
                        }
                        actions.setShouldCloseModal(true)
                    } else {
                        const updatedItem = await api.datasetItems.update(props.partialDatasetItem.id, {
                            ...props.partialDatasetItem,
                            input: coerceJsonToObject(formValues.input),
                            output: coerceJsonToObject(formValues.output),
                            metadata: coerceJsonToObject(formValues.metadata),
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

    defaults(({ props }): { datasetItemForm: DatasetItemFormValues } => {
        return {
            datasetItemForm: props.partialDatasetItem
                ? getDatasetItemFormDefaults(props.partialDatasetItem)
                : FORM_DEFAULT_VALUE,
        }
    }),

    propsChanged(({ props, actions }) => {
        if (!props.partialDatasetItem && props.isModalOpen) {
            actions.resetDatasetItemForm()
        }

        if (props.isModalOpen) {
            actions.setRefetchDatasetItems(false)
        }
    }),
])

export function getDatasetItemFormDefaults(partialDatasetItem: Partial<DatasetItem>): DatasetItemFormValues {
    return {
        input: prettifyJson(partialDatasetItem.input) || EMPTY_JSON,
        output: prettifyJson(partialDatasetItem.output) || EMPTY_JSON,
        metadata: prettifyJson(partialDatasetItem.metadata) || EMPTY_JSON,
    }
}
