import { actions, afterMount, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api, { ApiError, CountedPaginatedResponse } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'
import { Breadcrumb, Dataset, DatasetItem } from '~/types'

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

interface DatasetItemsFilters {
    page: number
    limit: number
}

export const DATASET_ITEMS_PER_PAGE = 50

function cleanFilters(values: Partial<DatasetItemsFilters>): DatasetItemsFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        limit: parseInt(String(values.limit)) || DATASET_ITEMS_PER_PAGE,
    }
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
        setFilters: (filters: Partial<DatasetItemsFilters>, debounce: boolean = true) => ({ filters, debounce }),
        deleteDatasetItem: (itemId: string) => ({ itemId }),
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
    })),

    loaders(({ props, values }) => ({
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
                        sceneLogic.findMounted()?.values.activeSceneId === 'LLMAnalyticsDatasets' &&
                        router.values.lastMethod !== 'POP' &&
                        values.datasetItems.results.length > 0 &&
                        values.rawFilters?.page !== filters.page
                    ) {
                        window.scrollTo(0, 0)
                    }

                    try {
                        const response = await api.datasetItems.list({
                            dataset: props.datasetId,
                            offset: Math.max(0, (filters.page - 1) * DATASET_ITEMS_PER_PAGE),
                            limit: DATASET_ITEMS_PER_PAGE,
                        })
                        return response
                    } catch (error) {
                        lemonToast.error('Failed to load dataset items')
                        throw error
                    }
                },
            },
        ],
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
                { name: 'LLM Analytics', path: urls.llmAnalyticsDashboard(), key: 'LLMAnalytics' },
                { name: 'Datasets', path: urls.llmAnalyticsDatasets(), key: 'LLMAnalyticsDatasets' },
                {
                    name: dataset && 'name' in dataset ? dataset.name : 'New Dataset',
                    key: 'LLMAnalyticsDataset',
                },
            ],
        ],

        datasetItemsCountLabel: [
            (s) => [s.filters, s.datasetItemsCount],
            (filters, count) => {
                const start = (filters.page - 1) * DATASET_ITEMS_PER_PAGE + 1
                const end = Math.min(filters.page * DATASET_ITEMS_PER_PAGE, count)

                return count === 0
                    ? '0 dataset items'
                    : `${start}-${end} of ${count} dataset item${count === 1 ? '' : 's'}`
            },
        ],
    }),

    listeners(({ actions, props, values, selectors, asyncActions }) => ({
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

        deleteDatasetItem: async ({ itemId }) => {
            if (props.datasetId !== 'new') {
                try {
                    await api.datasetItems.update(itemId, { deleted: true })
                    lemonToast.success('Dataset item deleted successfully')
                    actions.loadDatasetItems()
                } catch {
                    lemonToast.error('Failed to delete dataset item')
                }
            }
        },

        loadDatasetSuccess: ({ dataset }) => {
            if (isDataset(dataset)) {
                // Set form defaults when dataset is loaded
                actions.setDatasetFormValues(getDatasetFormDefaults(dataset))
            }
        },

        setFilters: async ({ debounce }, breakpoint, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const firstLoad = selectors.rawFilters(previousState) === null
            const { filters } = values

            if (
                debounce &&
                !firstLoad &&
                typeof filters.search !== 'undefined' &&
                filters.search !== oldFilters.search
            ) {
                await breakpoint(300)
            }

            if (firstLoad || !objectsEqual(oldFilters, filters)) {
                await asyncActions.loadDatasetItems(debounce)
            }
        },

        setActiveTab: ({ tab }) => {
            if (tab === DatasetTab.Items && props.datasetId !== 'new') {
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
            if (values.rawFilters === null) {
                actions.setFilters(cleanFilters(searchParams), false)
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
            actions.loadDatasetItems()
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
