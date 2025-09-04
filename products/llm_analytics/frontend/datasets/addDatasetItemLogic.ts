import { actions, afterMount, beforeUnmount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'

import api from '~/lib/api'
import { Dataset } from '~/types'

import type { addDatasetItemLogicType } from './addDatasetItemLogicType'

export interface AddDatasetItemLogicProps {
    traceId: string
    traceTimestamp: string
    traceSpanId: string
}

export const DATASETS_PER_PAGE = 100

export interface SearchFormValues {
    search: string
    datasetId: string | null
}

export const addDatasetItemLogic = kea<addDatasetItemLogicType>([
    path(['scenes', 'llm-analytics', 'addDatasetItemLogic']),

    props({ traceId: '', traceTimestamp: '', traceSpanId: '' } as AddDatasetItemLogicProps),

    actions({
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setEditMode: (editMode: 'add' | 'edit') => ({ editMode }),
        setDropdownVisible: (dropdownVisible: boolean) => ({ dropdownVisible }),
    }),

    reducers(() => ({
        isModalOpen: [
            false as boolean,
            {
                setIsModalOpen: (_, { isModalOpen }) => isModalOpen,
            },
        ],

        editMode: [
            'add' as 'add' | 'edit',
            {
                setEditMode: (_, { editMode }) => editMode,
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

    forms(({ asyncActions }) => ({
        searchForm: {
            defaults: { search: '', datasetId: null } as SearchFormValues,

            submit: async ({ datasetId }) => {
                if (datasetId) {
                } else {
                    await asyncActions.loadDatasets(true)
                }
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
