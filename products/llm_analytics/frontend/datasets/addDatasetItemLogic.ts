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
}

export const addDatasetItemLogic = kea<addDatasetItemLogicType>([
    path(['scenes', 'llm-analytics', 'addDatasetItemLogic']),

    props({ traceId: '', traceTimestamp: '', traceSpanId: '' } as AddDatasetItemLogicProps),

    actions({
        setIsModalOpen: (isModalOpen: boolean) => ({ isModalOpen }),
        setEditMode: (editMode: 'add' | 'edit') => ({ editMode }),
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
    })),

    selectors({
        datasets: [
            (s) => [s.datasetStore, s.searchForm],
            (datasetStore, searchForm): Dataset[] => {
                const storageKey = getStorageKey(searchForm.search)
                return datasetStore[storageKey] ?? []
            },
        ],
    }),

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
            defaults: {
                search: '',
            } as SearchFormValues,

            submit: async () => {
                await asyncActions.loadDatasets(true)
            },
        },
    })),

    listeners(({ actions }) => ({
        setIsModalOpen: () => {
            actions.setSearchFormValue('search', '')
        },

        setSearchFormValue: ({ name }) => {
            if (name === 'search') {
                actions.loadDatasets(true)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (!values.datasets.length) {
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
