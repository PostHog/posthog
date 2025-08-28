import { actions, afterMount, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api, { ApiError } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { urls } from '~/scenes/urls'
import { Breadcrumb, Dataset } from '~/types'

import type { llmAnalyticsDatasetLogicType } from './llmAnalyticsDatasetLogicType'
import { llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'

export interface DatasetLogicProps {
    datasetId: string | 'new'
}

export enum DatasetTab {
    Items = 'items',
    Metadata = 'metadata',
}

interface DatasetFormValues {
    name: string
    description: string
    metadata: string | null
}

function isDataset(dataset: Dataset | DatasetFormValues): dataset is Dataset {
    return 'id' in dataset
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

    reducers(({ props }) => ({
        dataset: [
            null as Dataset | DatasetFormValues | null,
            {
                loadDatasetSuccess: (_, { dataset }) => dataset,
                setDataset: (_, { dataset }) => dataset,
            },
        ],

        isEditingDataset: [
            props.datasetId === 'new',
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
    })),

    loaders(({ props }) => ({
        dataset: {
            loadDataset: async () => {
                try {
                    const dataset = await api.datasets.get(props.datasetId)
                    return dataset
                } catch (error) {
                    if (error instanceof ApiError && error.status === 404) {
                        lemonToast.error('Dataset not found')
                    } else {
                        lemonToast.error('Failed to load dataset')
                    }
                    throw error
                }
            },
        },
    })),

    forms(({ actions, props }) => ({
        datasetForm: {
            defaults: { name: '', description: '', metadata: '' } as DatasetFormValues,

            errors: ({ name, metadata }) => ({
                name: !name?.trim() ? 'Dataset name is required' : undefined,
                metadata: !isMetadataValid(metadata)
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
                            metadata: parseMetadata(formValues.metadata),
                        })
                        lemonToast.success('Dataset created successfully')
                        router.actions.replace(urls.llmAnalyticsDataset(savedDataset.id))
                    } else {
                        savedDataset = await api.datasets.update(props.datasetId, {
                            ...formValues,
                            metadata: parseMetadata(formValues.metadata),
                        })
                        lemonToast.success('Dataset updated successfully')
                        actions.editDataset(false)
                    }
                    actions.setDataset(savedDataset)
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

        datasetMissing: [
            (s) => [s.dataset, s.datasetLoading],
            (dataset, datasetLoading) => !datasetLoading && dataset === null,
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

    listeners(({ actions, props }) => ({
        deleteDataset: async () => {
            if (props.datasetId !== 'new') {
                try {
                    await api.datasets.update(props.datasetId, { deleted: true })
                    lemonToast.success('Dataset deleted successfully')
                    router.actions.replace(urls.llmAnalyticsDatasets())
                } catch {
                    lemonToast.error('Failed to delete dataset')
                }
            }
        },

        loadDatasetSuccess: ({ dataset }) => {
            if (isDataset(dataset)) {
                // Set form defaults when dataset is loaded
                actions.setDatasetFormValues(getDatasetFormDefaults(dataset))
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsDataset(':id')]: (_, searchParams) => {
            if (
                searchParams.tab &&
                Object.values(DatasetTab).includes(searchParams.tab as DatasetTab) &&
                searchParams.tab !== values.activeTab
            ) {
                actions.setActiveTab(searchParams.tab as DatasetTab)
            }
        },
    })),

    // TRICKY: Order matters here. Keep it in the bottom.
    defaults(({ props }) => {
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
    }),

    // TRICKY: Order matters here. Keep it in the bottom.
    afterMount(({ actions, values }) => {
        // Load dataset in any case, as it might be stale.
        if (!values.isNewDataset) {
            actions.loadDataset()
        }
    }),
])

/**
 * Coerce the metadata to a valid JSON object or null.
 * @param metadata - The metadata to coerce
 * @returns The coerced metadata or null
 */
function parseMetadata(metadata: string | null): Record<string, any> | null {
    if (!metadata) {
        return null
    }
    try {
        const parsedObject = JSON.parse(metadata)
        // Regular object or null
        if (typeof parsedObject === 'object') {
            return parsedObject as Record<string, any>
        }
        return null
    } catch {
        return null
    }
}

/**
 * Check if the metadata is a valid JSON object or is an empty string.
 * @param metadata - The metadata to check
 * @returns True if the metadata is valid, false otherwise
 */
function isMetadataValid(metadata: string | null): boolean {
    if (!metadata) {
        return true
    }
    try {
        const parsedMetadata = JSON.parse(metadata)
        if (typeof parsedMetadata !== 'object' || parsedMetadata === null) {
            return false
        }
    } catch {
        return false
    }
    return true
}

/**
 * Get default form values for a dataset.
 * @param dataset - The dataset to get the default form values for
 * @returns The default form values
 */
function getDatasetFormDefaults(dataset: Dataset): DatasetFormValues {
    const metadataPlaceholder = '{\n  \n}'
    let meta = dataset.metadata ? JSON.stringify(dataset.metadata, null, 2) : null
    if (meta === '{}') {
        meta = metadataPlaceholder
    }

    return {
        name: dataset.name,
        description: dataset.description || '',
        metadata: meta || metadataPlaceholder,
    }
}
