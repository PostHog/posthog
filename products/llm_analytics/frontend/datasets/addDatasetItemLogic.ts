import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { encodeParams, router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import api from '~/lib/api'
import { Dataset, DatasetItem } from '~/types'

import type { addDatasetItemLogicType } from './addDatasetItemLogicType'

export interface AddDatasetItemLogicProps {
    partialDatasetItem: Partial<DatasetItem> | null
}

export const DATASETS_PER_PAGE = 100

export interface SearchFormValues {
    search: string
    datasetId: string | null
}

export const addDatasetItemLogic = kea<addDatasetItemLogicType>([
    path(['scenes', 'llm-analytics', 'addDatasetItemLogic']),

    props({ partialDatasetItem: null } as AddDatasetItemLogicProps),

    actions({
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setEditMode: (editMode: 'create' | 'edit') => ({ editMode }),
        setDropdownVisible: (dropdownVisible: boolean) => ({ dropdownVisible }),
        setSelectedDataset: (dataset: Dataset | null) => ({ dataset }),
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
    })),

    loaders(({ values }) => ({
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
            (s) => [s.datasets, s.datasetStoreLoading],
            (datasets, datasetStoreLoading): boolean => {
                return !datasets && datasetStoreLoading
            },
        ],

        isModalMounted: [
            (s) => [s.editMode],
            (editMode): boolean => {
                return editMode === 'edit'
            },
        ],
    }),

    listeners(({ actions, asyncActions }) => ({
        setIsModalOpen: () => {
            actions.setSearchFormValue('search', '')
        },

        setSearchFormValue: ({ name }) => {
            if (name[0] === 'search') {
                asyncActions.loadDatasets(true)
            }
        },

        setDropdownVisible: ({ dropdownVisible }) => {
            if (dropdownVisible) {
                asyncActions.loadDatasets(true)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.datasets?.length) {
            actions.loadDatasets(false)
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
