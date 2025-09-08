import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { encodeParams, router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import api from '~/lib/api'
import { Dataset, DatasetItem } from '~/types'

import type { saveToDatasetButtonLogicType } from './saveToDatasetButtonLogicType'

export interface saveToDatasetButtonLogicProps {
    partialDatasetItem: Partial<DatasetItem> | null
}

export const DATASETS_PER_PAGE = 100
export const RECENT_DATASETS_LIMIT = 3

export interface SearchFormValues {
    search: string
    datasetId: string | null
}

export const saveToDatasetButtonLogic = kea<saveToDatasetButtonLogicType>([
    path(['scenes', 'llm-analytics', 'saveToDatasetButtonLogic']),

    props({ partialDatasetItem: null } as saveToDatasetButtonLogicProps),

    actions({
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setEditMode: (editMode: 'create' | 'edit') => ({ editMode }),
        setDropdownVisible: (dropdownVisible: boolean) => ({ dropdownVisible }),
        setSelectedDataset: (dataset: Dataset | null) => ({ dataset }),
        setRecentDatasetIds: (recentDatasetIds: string[]) => ({ recentDatasetIds }),
        setRecentDatasets: (recentDatasets: Dataset[]) => ({ recentDatasets }),
    }),

    reducers(() => ({
        isModalOpen: [
            false as boolean,
            {
                setIsModalOpen: (_, { isModalOpen }) => isModalOpen,
            },
        ],

        selectedDataset: [
            null as Dataset | null,
            {
                setSelectedDataset: (_, { dataset }) => dataset,
            },
        ],

        editMode: [
            'create' as 'create' | 'edit',
            {
                setEditMode: (_, { editMode }) => editMode,
                setIsModalOpen: (state, { isModalOpen }) => (isModalOpen ? state : 'create'),
            },
        ],

        dropdownVisible: [
            false as boolean,
            {
                setDropdownVisible: (_, { dropdownVisible }) => dropdownVisible,
            },
        ],

        recentDatasetIds: [
            [] as string[],
            { persist: true },
            {
                setRecentDatasetIds: (_, { recentDatasetIds }) => truncateRecentDatasets(recentDatasetIds),
            },
        ],

        recentDatasets: [
            [] as Dataset[],
            {
                setRecentDatasets: (_, { recentDatasets }) => truncateRecentDatasets(recentDatasets),
            },
        ],
    })),

    loaders(({ actions, values }) => ({
        datasetStore: [
            {} as Record<string, Dataset[]>,
            {
                loadDatasets: async (debounce: boolean = false, breakpoint) => {
                    if (debounce) {
                        await breakpoint(300)
                    }

                    const params = {
                        limit: DATASETS_PER_PAGE,
                        offset: 0,
                        search: values.searchForm.search,
                    }
                    const storageKey = getStorageKey(values.searchForm.search)
                    const response = await api.datasets.list(params)
                    return {
                        ...values.datasetStore,
                        [storageKey]: response.results,
                    }
                },
            },
        ],

        recentDatasets: [
            [] as Dataset[],
            {
                loadRecentDatasets: async (debounce: boolean = false, breakpoint) => {
                    if (debounce) {
                        await breakpoint(300)
                    }

                    if (values.recentDatasetIds.length === 0) {
                        return []
                    }

                    try {
                        const response = await api.datasets.list({
                            ids: values.recentDatasetIds,
                        })

                        const map = new Map(response.results.map((dataset) => [dataset.id, dataset]))

                        // Preserve the original order of the recent dataset ids.
                        const missingIds = values.recentDatasetIds.filter((id) => !map.has(id))
                        const actualItems = values.recentDatasetIds.filter((id) => map.has(id))

                        if (missingIds.length > 0) {
                            actions.setRecentDatasetIds(actualItems)
                        }

                        return actualItems.map((id) => map.get(id)!)
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),

    forms(({ asyncActions, actions, values, props }) => ({
        searchForm: {
            defaults: { search: '', datasetId: null } as SearchFormValues,

            submit: async ({ datasetId }) => {
                // Dataset is not selected. Submit from the search input.
                if (!datasetId) {
                    await asyncActions.loadDatasets(true)
                    return
                }

                // Close the dropdown.
                actions.setDropdownVisible(false)
                actions.resetSearchForm()

                // Find the selected dataset. Practically, this should always be found.
                const dataset = values.datasets?.find((dataset) => dataset.id === datasetId)
                if (!dataset) {
                    return
                }

                if (values.editMode === 'edit') {
                    // Open the modal.
                    actions.setSelectedDataset(dataset)
                    actions.setIsModalOpen(true)
                    return
                }

                async function createDatasetItem(datasetId: string, recursionCount: number = 0): Promise<void> {
                    try {
                        await api.datasetItems.create({
                            ...props.partialDatasetItem,
                            dataset: datasetId,
                        })
                        lemonToast.success('Dataset item has been created successfully', {
                            button: {
                                label: 'View',
                                action: () => {
                                    router.actions.push(urls.llmAnalyticsDataset(datasetId))
                                },
                            },
                        })
                    } catch {
                        lemonToast.error('Failed to create dataset item', {
                            button:
                                recursionCount < 3
                                    ? {
                                          label: 'Retry',
                                          action: () => {
                                              createDatasetItem(datasetId, recursionCount + 1)
                                          },
                                      }
                                    : undefined,
                        })
                    }
                }

                await createDatasetItem(datasetId)
            },
        },
    })),

    selectors({
        datasets: [
            (s) => [s.datasetStore, s.searchForm],
            (datasetStore, searchForm): Dataset[] | null => {
                const storageKey = getStorageKey(searchForm.search)
                return datasetStore[storageKey] ?? null
            },
        ],

        isLoadingDatasets: [
            (s) => [s.datasets, s.datasetStoreLoading, s.recentDatasetsLoading],
            (datasets, datasetStoreLoading, recentDatasetsLoading): boolean => {
                return !datasets && (datasetStoreLoading || recentDatasetsLoading)
            },
        ],

        isModalMounted: [
            (s) => [s.editMode],
            (editMode): boolean => {
                return editMode === 'edit'
            },
        ],
    }),

    listeners(({ actions, asyncActions, values }) => ({
        setIsModalOpen: () => {
            actions.setSearchFormValue('search', '')
        },

        setSearchFormValue: ({ name, value }) => {
            if (compareFieldName(name, 'search')) {
                asyncActions.loadDatasets(true)
            }

            if (compareFieldName(name, 'datasetId') && !values.recentDatasetIds.includes(value)) {
                const dataset = values.datasets?.find((dataset) => dataset.id === value)
                if (dataset) {
                    actions.setRecentDatasetIds([value, ...values.recentDatasetIds])
                    actions.setRecentDatasets([dataset, ...values.recentDatasets])
                }
            }
        },

        setDropdownVisible: ({ dropdownVisible }) => {
            if (dropdownVisible) {
                asyncActions.loadDatasets(true)
            } else {
                actions.setSearchFormValue('search', '')
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.datasets?.length) {
            actions.loadDatasets(false)
            actions.loadRecentDatasets(false)
        }
    }),

    beforeUnmount(({ actions }) => {
        actions.setSearchFormValue('search', '')
    }),
])

export function getStorageKey(search: string): string {
    return encodeParams({
        limit: DATASETS_PER_PAGE,
        offset: 0,
        search,
    })
}

/**
 * Truncates the recent datasets to the first 3.
 * @param state - The current state.
 * @returns The updated state.
 */
export function truncateRecentDatasets<T>(state: T[]): T[] {
    return state.slice(0, RECENT_DATASETS_LIMIT)
}

/**
 * A field name from kea-forms is either a string or an array of strings. This function compares the name to the field name.
 * @param nameValue - The name to compare.
 * @param fieldName - The field name to compare.
 * @returns boolean
 */
export function compareFieldName(nameValue: string | number | (string | number)[], fieldName: string): boolean {
    if (Array.isArray(nameValue)) {
        return nameValue[0] === fieldName
    }
    return nameValue === fieldName
}
