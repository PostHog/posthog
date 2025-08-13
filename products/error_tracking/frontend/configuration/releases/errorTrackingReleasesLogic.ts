import {
    actions,
    AnyFunction,
    defaults,
    kea,
    listeners,
    LogicBuilder,
    LogicWrapper,
    MakeLogicType,
    path,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { PaginationManual } from '@posthog/lemon-ui'

interface Values {
    page: number
    releaseResponse: ErrorTrackingReleaseResponse | null
    releases: ErrorTrackingRelease[]
    pagination: PaginationManual
    releaseResponseLoading: boolean
}

interface Actions extends Record<string, AnyFunction> {
    loadReleases: () => void
    deleteRelease: (id: string) => { id: string }
    setPage: (page: number) => { page: number }
}

export const RESULTS_PER_PAGE = 15

export interface ErrorTrackingReleaseResponse extends CountedPaginatedResponse<ErrorTrackingRelease> {}

// typegen does not work here, creates a wrapper to avoid typegen from overriding types here.
function createKea<V extends Record<string, any>, A extends Record<string, AnyFunction>, P extends Record<string, any>>(
    inputs: LogicBuilder<MakeLogicType<V, A, P>>[]
): LogicWrapper<MakeLogicType<V, A, P>> {
    return kea<MakeLogicType<V, A, P>>(inputs)
}

export const errorTrackingReleasesLogic = createKea<Values, Actions, {}>([
    path(['scenes', 'error-tracking', 'errorTrackingReleasesLogic']),

    actions({
        loadReleases: () => ({}),
        deleteRelease: (id: string) => ({ id }),
        setPage: (page: number) => ({ page }),
    }),

    defaults({
        page: 1 as number,
        releaseResponse: null as ErrorTrackingReleaseResponse | null,
    }),

    reducers({
        page: {
            setPage: (_, { page }) => page,
        },
    }),

    loaders(({ values }) => ({
        releaseResponse: {
            loadReleases: async (_, breakpoint) => {
                await breakpoint(100)
                const res = await api.errorTracking.releases.list({
                    limit: RESULTS_PER_PAGE,
                    offset: (values.page - 1) * RESULTS_PER_PAGE,
                    orderBy: '-created_at',
                })
                return res as ErrorTrackingReleaseResponse
            },
        },
    })),

    selectors(({ actions }) => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ErrorTracking,
                    name: 'Error tracking',
                    path: urls.errorTracking(),
                },
                {
                    key: Scene.ErrorTrackingConfiguration,
                    name: 'Configuration',
                },
            ],
        ],
        releases: [
            (s) => [s.releaseResponse],
            (response: ErrorTrackingReleaseResponse): ErrorTrackingRelease[] => {
                return response?.results || []
            },
        ],
        pagination: [
            (s) => [s.page, s.releaseResponse],
            (page: number, releaseResponse: ErrorTrackingReleaseResponse): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: RESULTS_PER_PAGE,
                    currentPage: page,
                    entryCount: releaseResponse?.count ?? 0,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                } as PaginationManual
            },
        ],
    })),

    listeners(({ actions }) => ({
        deleteRelease: async ({ id }: { id: ErrorTrackingRelease['id'] }) => {
            await api.errorTracking.releases.delete(id)
            actions.loadReleases()
        },
        setPage: () => actions.loadReleases(),
    })),
])
