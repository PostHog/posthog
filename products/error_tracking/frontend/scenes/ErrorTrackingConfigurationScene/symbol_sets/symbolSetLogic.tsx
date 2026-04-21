import { actions, afterMount, defaults, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ErrorTrackingSymbolSet, SymbolSetStatusFilter } from 'lib/components/Errors/types'
import { pluralize } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { symbolSetLogicType } from './symbolSetLogicType'

export const RESULTS_PER_PAGE = 20

export type ErrorTrackingSymbolSetResponse = CountedPaginatedResponse<ErrorTrackingSymbolSet>
export type SymbolSetOrder = 'created_at' | '-created_at' | 'last_used' | '-last_used'

export const symbolSetLogic = kea<symbolSetLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingConfigurationScene', 'symbol_sets', 'symbolSetLogic']),

    actions({
        loadSymbolSets: () => {},
        setSymbolSetStatusFilter: (status: SymbolSetStatusFilter) => ({ status }),
        setSymbolSetOrder: (order: SymbolSetOrder) => ({ order }),
        setPage: (page: number) => ({ page }),
        setSelectedSymbolSetIds: (ids: string[]) => ({ ids }),
        setShiftKeyHeld: (shiftKeyHeld: boolean) => ({ shiftKeyHeld }),
        setPreviouslyCheckedIndex: (index: number) => ({ index }),
    }),

    defaults({
        page: 1 as number,
        symbolSetResponse: null as ErrorTrackingSymbolSetResponse | null,
        symbolSetStatusFilter: 'all' as SymbolSetStatusFilter,
        symbolSetOrder: '-created_at' as SymbolSetOrder,
        selectedSymbolSetIds: [] as string[],
        deleteSymbolSetResponse: null as null,
        shiftKeyHeld: false as boolean,
        previouslyCheckedIndex: null as number | null,
    }),

    reducers({
        symbolSetStatusFilter: {
            setSymbolSetStatusFilter: (_, { status }) => status,
        },
        page: {
            setPage: (_, { page }) => page,
            setSymbolSetStatusFilter: () => 1,
            setSymbolSetOrder: () => 1,
        },
        symbolSetOrder: {
            setSymbolSetOrder: (_, { order }) => order,
        },
        selectedSymbolSetIds: {
            setSelectedSymbolSetIds: (_, { ids }) => ids,
            loadSymbolSets: () => [],
        },
        shiftKeyHeld: {
            setShiftKeyHeld: (_, { shiftKeyHeld }) => shiftKeyHeld,
        },
        previouslyCheckedIndex: {
            setPreviouslyCheckedIndex: (_, { index }) => index,
            loadSymbolSets: () => null,
        },
    }),

    loaders(({ values, actions }) => ({
        symbolSetResponse: {
            loadSymbolSets: async (_, breakpoint) => {
                await breakpoint(100)
                const res = await api.errorTracking.symbolSets.list({
                    status: values.symbolSetStatusFilter,
                    limit: RESULTS_PER_PAGE,
                    offset: (values.page - 1) * RESULTS_PER_PAGE,
                    orderBy: values.symbolSetOrder,
                })
                return res
            },
        },
        deleteSymbolSetResponse: {
            deleteSymbolSet: async (id: string) => {
                await api.errorTracking.symbolSets.delete(id)
                lemonToast.success('Symbol set deleted')
                actions.loadSymbolSets()
                return null
            },
            bulkDeleteSymbolSets: async () => {
                const ids = values.selectedSymbolSetIds
                await api.errorTracking.symbolSets.bulkDelete(ids)
                lemonToast.success(`${ids.length} ${pluralize(ids.length, 'symbol set', 'symbol sets', false)} deleted`)
                actions.loadSymbolSets()
                return null
            },
        },
    })),

    listeners(({ actions }) => ({
        setSymbolSetStatusFilter: () => actions.loadSymbolSets(),
        setPage: () => actions.loadSymbolSets(),
        setSymbolSetOrder: () => actions.loadSymbolSets(),
    })),

    selectors({
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
                    key: 'error-tracking-configuration',
                    name: 'Configuration',
                    iconType: 'error_tracking',
                },
            ],
        ],
    }),

    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            const onKeyChange = (event: KeyboardEvent): void => {
                actions.setShiftKeyHeld(event.shiftKey)
            }
            window.addEventListener('keydown', onKeyChange)
            window.addEventListener('keyup', onKeyChange)
            return () => {
                window.removeEventListener('keydown', onKeyChange)
                window.removeEventListener('keyup', onKeyChange)
            }
        }, 'shiftKeyListener')
    }),
])
