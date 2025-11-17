import { actions, afterMount, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api, { CountedPaginatedResponse } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'
import { Breadcrumb, Dataset, DatasetItem } from '~/types'

import { truncateValue } from '../utils'
import type { llmAnalyticsDatasetLogicType } from './llmAnalyticsDatasetLogicType'
import { llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'
import { EMPTY_JSON, coerceJsonToObject, isStringJsonObject, prettifyJson } from './utils'

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

export interface DatasetItemsFilters {
    page: number
    limit: number
}

export const DATASET_ITEMS_PER_PAGE = 50

export function isDataset(dataset: Dataset | DatasetFormValues | null): dataset is Dataset {
    return dataset !== null && 'id' in dataset
}

function cleanFilters(values: Partial<DatasetItemsFilters>): DatasetItemsFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        limit: parseInt(String(values.limit)) || DATASET_ITEMS_PER_PAGE,
    }
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
        // beforeUnmount doesn't work as expected for scenes.
        onUnmount: true,
        setFilters: (filters: Partial<DatasetItemsFilters>, debounce: boolean = true) => ({ filters, debounce }),
        deleteDatasetItem: (itemId: string) => ({ itemId }),
        triggerDatasetItemModal: (open: boolean) => ({ open }),
        setSelectedDatasetItem: (datasetItem: DatasetItem) => ({ datasetItem }),
        closeModalAndRefetchDatasetItems: (refetchDatasetItems?: boolean) => ({ refetchDatasetItems }),
        setDeletingDataset: (deleting: boolean) => ({ deleting }),
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

        rawFilters: [
            null as Partial<DatasetItemsFilters> | null,
            {
                setFilters: (state, { filters }) =>
                    cleanFilters({
                        ...state,
                        ...filters,
                        // Reset page on filter change except if it's page that's being updated
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],

        isDatasetItemModalOpen: [
            false as boolean,
            {
                triggerDatasetItemModal: (_, { open }) => open,
                closeModalAndRefetchDatasetItems: () => false,
            },
        ],

        selectedDatasetItem: [
            null as DatasetItem | null,
            {
                setSelectedDatasetItem: (_, { datasetItem }) => datasetItem,
                // Reset the selected dataset item when the modal is closed
                triggerDatasetItemModal: (state, { open }) => (open ? state : null),
                closeModalAndRefetchDatasetItems: () => null,
            },
        ],

        isDeletingDataset: [
            false as boolean,
            {
                setDeletingDataset: (_, { deleting }) => deleting,
                deleteDataset: () => true,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        dataset: {
            __default: null as Dataset | DatasetFormValues | null,
            loadDataset: () => {
                return api.datasets.get(props.datasetId)
            },
        },

        datasetItems: [
            { results: [], count: 0, offset: 0 } as CountedPaginatedResponse<DatasetItem>,
            {
                loadDatasetItems: async (debounce: boolean = false, breakpoint) => {
                    if (debounce && values.datasetItems.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values

                    // Scroll to top if the page changed, except if changed via back/forward
                    if (
                        sceneLogic.findMounted()?.values.activeSceneId === 'LLMAnalyticsDataset' &&
                        router.values.lastMethod !== 'POP' &&
                        values.datasetItems.results.length > 0 &&
                        values.rawFilters?.page !== filters.page
                    ) {
                        window.scrollTo(0, 0)
                    }

                    const response = await api.datasetItems.list({
                        dataset: props.datasetId,
                        offset: Math.max(0, (filters.page - 1) * DATASET_ITEMS_PER_PAGE),
                        limit: DATASET_ITEMS_PER_PAGE,
                    })
                    return response
                },
            },
        ],
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
                            metadata: coerceJsonToObject(formValues.metadata),
                        })
                        lemonToast.success('Dataset created successfully')
                        router.actions.replace(urls.llmAnalyticsDataset(savedDataset.id))
                    } else {
                        savedDataset = await api.datasets.update(props.datasetId, {
                            ...formValues,
                            metadata: coerceJsonToObject(formValues.metadata),
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

        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<DatasetItemsFilters> | null): DatasetItemsFilters => cleanFilters(rawFilters || {}),
        ],

        datasetItemsCount: [
            (s) => [s.datasetItems],
            (datasetItems: CountedPaginatedResponse<DatasetItem>) => datasetItems.count,
        ],

        pagination: [
            (s) => [s.filters, s.datasetItemsCount],
            (filters: DatasetItemsFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: filters.limit,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        breadcrumbs: [
            (s) => [s.dataset],
            (dataset): Breadcrumb[] => [
                {
                    name: 'LLM Analytics',
                    path: urls.llmAnalyticsDashboard(),
                    key: 'LLMAnalytics',
                    iconType: 'llm_analytics',
                },
                {
                    name: 'Datasets',
                    path: urls.llmAnalyticsDatasets(),
                    key: 'LLMAnalyticsDatasets',
                    iconType: 'llm_analytics',
                },
                {
                    name: dataset && 'name' in dataset ? dataset.name : 'New Dataset',
                    key: 'LLMAnalyticsDataset',
                    iconType: 'llm_analytics',
                },
            ],
        ],
    }),

    listeners(({ actions, props, values, selectors, asyncActions }) => ({
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
                actions.setDeletingDataset(false)
            }
        },

        onUnmount: () => {
            if (props.datasetId === 'new') {
                // Reset form values when creating a new dataset
                actions.setDatasetFormValues(DEFAULT_DATASET_FORM_VALUES)
            } else {
                // Set form values when editing an existing dataset
                const existingDataset = findExistingDataset(props.datasetId)
                if (existingDataset) {
                    actions.setDatasetFormValues(getDatasetFormDefaults(existingDataset))
                } else {
                    actions.setDatasetFormValues(DEFAULT_DATASET_FORM_VALUES)
                }
            }
        },

        deleteDatasetItem: async ({ itemId }) => {
            if (props.datasetId !== 'new') {
                try {
                    await api.datasetItems.update(itemId, { deleted: true })
                    lemonToast.info(`Dataset item ${truncateValue(itemId)} has been deleted.`, {
                        button: {
                            label: 'Undo',
                            dataAttr: 'undo-delete-dataset-item',
                            action: async () => {
                                await api.datasetItems.update(itemId, { deleted: false })
                                await asyncActions.loadDatasetItems(false)
                            },
                        },
                    })
                    await asyncActions.loadDatasetItems(false)
                } catch {
                    lemonToast.error('Failed to delete dataset item')
                }
            }
        },

        loadDatasetSuccess: ({ dataset }) => {
            if (!values.isEditingDataset) {
                // Set form defaults when dataset is loaded
                actions.setDatasetFormValues(getDatasetFormDefaults(dataset))
            }
        },

        loadDatasetItemsSuccess: ({ datasetItems }) => {
            if (router.values.searchParams.item) {
                const item = datasetItems.results.find((item) => item.id === router.values.searchParams.item)
                if (item && values.selectedDatasetItem !== item) {
                    actions.setSelectedDatasetItem(item)
                    actions.triggerDatasetItemModal(true)
                }
            }
        },

        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const { filters } = values

            if (!objectsEqual(oldFilters, filters)) {
                await asyncActions.loadDatasetItems(debounce)
            }
        },

        setActiveTab: ({ tab }) => {
            if (tab === DatasetTab.Items && props.datasetId !== 'new') {
                actions.loadDatasetItems(true)
            }
        },

        closeModalAndRefetchDatasetItems: ({ refetchDatasetItems }) => {
            if (refetchDatasetItems) {
                actions.loadDatasetItems()
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

            // Set default filters if they're not set yet
            const newFilters = cleanFilters(searchParams)
            if (values.rawFilters === null || !objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            }

            // Open the dataset item modal if the item is set in the URL
            if (searchParams.item) {
                const item = values.datasetItems.results.find((item) => item.id === searchParams.item)
                if (item) {
                    actions.setSelectedDatasetItem(item)
                    actions.triggerDatasetItemModal(true)
                }
            }
        },
    })),

    actionToUrl(({ values }) => ({
        closeModalAndRefetchDatasetItems: () => {
            const searchParams = router.values.searchParams
            const nextSearchParams = { ...searchParams, item: undefined }
            return [
                urls.llmAnalyticsDataset(isDataset(values.dataset) ? values.dataset.id : 'new'),
                nextSearchParams,
                {},
                { replace: false },
            ]
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
            if (props.datasetId === 'new') {
                return {
                    dataset: DEFAULT_DATASET_FORM_VALUES,
                    datasetForm: DEFAULT_DATASET_FORM_VALUES,
                }
            }

            // Don't show a loader if the dataset has already been loaded.
            const existingDataset = findExistingDataset(props.datasetId)
            if (existingDataset) {
                return {
                    dataset: existingDataset,
                    datasetForm: getDatasetFormDefaults(existingDataset),
                }
            }

            return {
                dataset: null,
                datasetForm: DEFAULT_DATASET_FORM_VALUES,
            }
        }
    ),

    // TRICKY: Order matters here. Keep it in the bottom.
    afterMount(({ actions, values }) => {
        // Load dataset in any case, as it might be stale.
        if (!values.isNewDataset) {
            actions.loadDataset()
            actions.loadDatasetItems()
        }
    }),
])

const DEFAULT_DATASET_FORM_VALUES: DatasetFormValues = {
    name: '',
    description: '',
    metadata: '{\n  \n}',
}

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

/**
 * Find an existing dataset in the datasets logic.
 * @param datasetId - The ID of the dataset to find
 * @returns The dataset if found, undefined otherwise
 */
function findExistingDataset(datasetId: string): Dataset | undefined {
    return llmAnalyticsDatasetsLogic.findMounted()?.values.datasets.results.find((dataset) => dataset.id === datasetId)
}
