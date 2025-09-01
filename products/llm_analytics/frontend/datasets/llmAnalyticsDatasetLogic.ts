import { actions, afterMount, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { urls } from '~/scenes/urls'
import { Breadcrumb, Dataset } from '~/types'

import type { llmAnalyticsDatasetLogicType } from './llmAnalyticsDatasetLogicType'
import { llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'
import { EMPTY_JSON, corseJsonToObject, isStringJsonObject, prettifyJson } from './utils'

export interface DatasetLogicProps {
    datasetId: string | 'new'
}

export enum DatasetTab {
    Items = 'items',
    Metadata = 'metadata',
}

export interface DatasetFormValues {
    name: string
    description: string
    metadata: string | null
}

export const DATASET_ITEMS_PER_PAGE = 50

export function isDataset(dataset: Dataset | DatasetFormValues | null): dataset is Dataset {
    return dataset !== null && 'id' in dataset
}

export const llmAnalyticsDatasetLogic = kea<llmAnalyticsDatasetLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsDatasetLogic']),

    props({ datasetId: 'new' } as DatasetLogicProps),

    key(({ datasetId }) => `dataset-${datasetId}`),

    actions({
        setDataset: (dataset: Dataset | DatasetFormValues) => ({ dataset }),
        editDataset: (editing: boolean) => ({ editing }),
        deleteDataset: true,
        setActiveTab: (tab: DatasetTab) => ({ tab }),
    }),

    reducers({
        dataset: [
            null as Dataset | DatasetFormValues | null,
            {
                loadDatasetSuccess: (_, { dataset }) => dataset,
                setDataset: (_, { dataset }) => dataset,
            },
        ],

        isEditingDataset: [
            false as boolean,
            {
                editDataset: (_, { editing }) => editing,
            },
        ],

        activeTab: [
            DatasetTab.Items as DatasetTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),

    loaders(({ props }) => ({
        dataset: {
            __default: null as Dataset | DatasetFormValues | null,
            loadDataset: () => {
                return api.datasets.get(props.datasetId)
            },
        },
    })),

    forms(({ actions, props }) => ({
        datasetForm: {
            defaults: { name: '', description: '', metadata: '' } as DatasetFormValues,

            errors: ({ name, metadata }) => ({
                name: !name?.trim() ? 'Dataset name is required' : undefined,
                metadata: !isStringJsonObject(metadata)
                    ? 'Dataset metadata must contain a valid JSON object or be empty'
                    : undefined,
            }),

            submit: async (formValues) => {
                const isNew = props.datasetId === 'new'
                try {
                    let savedDataset: Dataset
                    if (isNew) {
                        savedDataset = await api.datasets.create({
                            name: formValues.name,
                            description: formValues.description,
                            metadata: corseJsonToObject(formValues.metadata),
                        })
                        lemonToast.success('Dataset created successfully')
                        router.actions.replace(urls.llmAnalyticsDataset(savedDataset.id))
                    } else {
                        savedDataset = await api.datasets.update(props.datasetId, {
                            ...formValues,
                            metadata: corseJsonToObject(formValues.metadata),
                        })
                        lemonToast.success('Dataset updated successfully')
                    }
                    actions.setDataset(savedDataset)
                    actions.editDataset(false)
                    actions.setDatasetFormValues(getDatasetFormDefaults(savedDataset))
                } catch (error: any) {
                    const message = error?.detail || 'Failed to save dataset'
                    lemonToast.error(message)
                    throw error
                }
            },
        },
    })),

    selectors({
        isNewDataset: [() => [(_, props) => props], (props) => props.datasetId === 'new'],

        isDatasetMissing: [
            (s) => [s.dataset, s.datasetLoading],
            (dataset, datasetLoading) => !datasetLoading && dataset === null,
        ],

        shouldDisplaySkeleton: [
            (s) => [s.dataset, s.datasetLoading],
            (dataset, datasetLoading) => !dataset && datasetLoading,
        ],

        breadcrumbs: [
            (s) => [s.dataset],
            (dataset): Breadcrumb[] => [
                { name: 'LLM Analytics', path: urls.llmAnalyticsDashboard(), key: 'LLMAnalytics' },
                { name: 'Datasets', path: urls.llmAnalyticsDatasets(), key: 'LLMAnalyticsDatasets' },
                {
                    name: dataset && 'name' in dataset ? dataset.name : 'New Dataset',
                    key: 'LLMAnalyticsDataset',
                },
            ],
        ],
    }),

    listeners(({ actions, props, values }) => ({
        deleteDataset: async () => {
            if (props.datasetId !== 'new') {
                try {
                    await api.datasets.update(props.datasetId, { deleted: true })
                    lemonToast.info(`${values.dataset?.name || 'Dataset'} has been deleted.`, {
                        button: {
                            label: 'Undo',
                            dataAttr: 'undo-delete-dataset',
                            action: async () => {
                                await api.datasets.update(props.datasetId, { deleted: false })
                            },
                        },
                    })
                    router.actions.replace(urls.llmAnalyticsDatasets())
                } catch {
                    lemonToast.error('Failed to delete dataset')
                }
            }
        },

        loadDatasetSuccess: ({ dataset }) => {
            // Set form defaults when dataset is loaded
            actions.setDatasetFormValues(getDatasetFormDefaults(dataset))
        },

        setActiveTab: ({ tab }) => {
            if (tab === DatasetTab.Items && props.datasetId !== 'new') {
                actions.loadDatasetItems(true)
            }
        },
    })),

    // TRICKY: Order matters here. Keep it in the bottom.
    defaults(
        ({
            props,
        }): {
            dataset: DatasetFormValues | Dataset | null
            datasetForm: DatasetFormValues
        } => {
            const defaultDataset: DatasetFormValues = {
                name: '',
                description: '',
                metadata: '{\n  \n}',
            }

            if (props.datasetId === 'new') {
                return {
                    dataset: defaultDataset,
                    datasetForm: defaultDataset,
                }
            }

            // Don't show a loader if the dataset has already been loaded.
            const existingDataset = llmAnalyticsDatasetsLogic
                .findMounted()
                ?.values.datasets.results.find((dataset) => dataset.id === props.datasetId)

            if (existingDataset) {
                return {
                    dataset: existingDataset,
                    datasetForm: getDatasetFormDefaults(existingDataset),
                }
            }

            return {
                dataset: null,
                datasetForm: defaultDataset,
            }
        }
    ),

    // TRICKY: Order matters here. Keep it in the bottom.
    afterMount(({ actions, values }) => {
        // Load dataset in any case, as it might be stale.
        if (!values.isNewDataset) {
            actions.loadDataset()
        }
    }),
])

/**
 * Get default form values for a dataset.
 * @param dataset - The dataset to get the default form values for
 * @returns The default form values
 */
function getDatasetFormDefaults(dataset: Dataset): DatasetFormValues {
    return {
        name: dataset.name,
        description: dataset.description || '',
        metadata: prettifyJson(dataset.metadata) || EMPTY_JSON,
    }
}
