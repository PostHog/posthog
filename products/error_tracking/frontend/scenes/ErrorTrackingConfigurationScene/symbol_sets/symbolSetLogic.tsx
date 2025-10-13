import { actions, defaults, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ErrorTrackingSymbolSet, SymbolSetStatusFilter } from 'lib/components/Errors/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { symbolSetLogicType } from './symbolSetLogicType'

export type SymbolSetUpload = SourceMapUpload
export const RESULTS_PER_PAGE = 20

export type SourceMapUpload = {
    minified: File
    sourceMap: File
}

export type ErrorTrackingSymbolSetResponse = CountedPaginatedResponse<ErrorTrackingSymbolSet>

export const symbolSetLogic = kea<symbolSetLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingConfigurationScene', 'symbol_sets', 'symbolSetLogic']),

    actions({
        loadSymbolSets: () => {},
        deleteSymbolSet: (id: string) => ({ id }),
        setUploadSymbolSetId: (id: string | null) => ({ id }),
        setSymbolSetStatusFilter: (status: SymbolSetStatusFilter) => ({ status }),
        setPage: (page: number) => ({ page }),
    }),

    defaults({
        page: 1 as number,
        symbolSetResponse: null as ErrorTrackingSymbolSetResponse | null,
        symbolSetStatusFilter: 'all' as SymbolSetStatusFilter,
        uploadSymbolSetId: null as string | null,
    }),

    reducers({
        uploadSymbolSetId: {
            setUploadSymbolSetId: (_, { id }) => id,
        },
        symbolSetStatusFilter: {
            setSymbolSetStatusFilter: (_, { status }) => status,
        },
        page: {
            setPage: (_, { page }) => page,
            setSymbolSetStatusFilter: () => 1,
        },
    }),

    loaders(({ values }) => ({
        symbolSetResponse: {
            loadSymbolSets: async (_, breakpoint) => {
                await breakpoint(100)
                const res = await api.errorTracking.symbolSets.list({
                    status: values.symbolSetStatusFilter,
                    limit: RESULTS_PER_PAGE,
                    offset: (values.page - 1) * RESULTS_PER_PAGE,
                })
                return res
            },
        },
    })),

    forms(({ values, actions }) => ({
        uploadSymbolSet: {
            defaults: { minified: [], sourceMap: [] } as { minified: File[]; sourceMap: File[] },
            submit: async ({ minified, sourceMap }) => {
                if (minified.length < 1 || sourceMap.length < 1) {
                    lemonToast.error('Please select both a minified file and a source map file')
                    return
                }

                const minifiedSrc = minified[0]
                const sourceMapSrc = sourceMap[0]
                const id = values.uploadSymbolSetId

                if (id == null) {
                    return
                }

                const formData = new FormData()
                formData.append('minified', minifiedSrc)
                formData.append('source_map', sourceMapSrc)
                await api.errorTracking.symbolSets.update(id, formData)
                actions.setUploadSymbolSetId(null)
                actions.loadSymbolSets()
                actions.resetUploadSymbolSet()
                lemonToast.success('Source map uploaded')
            },
        },
    })),

    listeners(({ actions }) => ({
        deleteSymbolSet: async ({ id }: { id: ErrorTrackingSymbolSet['id'] }) => {
            await api.errorTracking.symbolSets.delete(id)
            lemonToast.success('Symbol set deleted')
            actions.loadSymbolSets()
        },
        setSymbolSetStatusFilter: () => actions.loadSymbolSets(),
        setPage: () => actions.loadSymbolSets(),
    })),

    selectors(({ actions }) => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    name: 'Error tracking',
                    path: urls.errorTracking(),
                    iconType: 'error_tracking',
                },
                {
                    key: Scene.ErrorTrackingConfiguration,
                    name: 'Configuration',
                    iconType: 'error_tracking',
                },
            ],
        ],
        symbolSets: [
            (s) => [s.symbolSetResponse],
            (response: ErrorTrackingSymbolSetResponse): ErrorTrackingSymbolSet[] => {
                return response?.results || []
            },
        ],
        pagination: [
            (s) => [s.page, s.symbolSetResponse],
            (page: number, symbolSetResponse: ErrorTrackingSymbolSetResponse) => {
                return {
                    controlled: true,
                    pageSize: RESULTS_PER_PAGE,
                    currentPage: page,
                    entryCount: symbolSetResponse?.count ?? 0,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
    })),
])
