import { actions, defaults, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { errorTrackingReleasesLogicType } from './errorTrackingReleasesLogicType'

export const RESULTS_PER_PAGE = 20

export type ErrorTrackingReleaseResponse = CountedPaginatedResponse<ErrorTrackingRelease>

export const errorTrackingReleasesLogic = kea<errorTrackingReleasesLogicType>([
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
            loadReleases: () => 1,
        },
    }),

    loaders(({ values }) => ({
        releaseResponse: {
            loadReleases: async (_, breakpoint) => {
                await breakpoint(100)
                const res = await api.errorTracking.releases.list({
                    limit: RESULTS_PER_PAGE,
                    offset: (values.page - 1) * RESULTS_PER_PAGE,
                })
                return res
            },
        },
    })),

    listeners(({ actions }) => ({
        deleteRelease: async ({ id }: { id: ErrorTrackingRelease['id'] }) => {
            await api.errorTracking.releases.delete(id)
            actions.loadReleases()
        },
        setPage: () => actions.loadReleases(),
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
            (page: number, releaseResponse: ErrorTrackingReleaseResponse) => {
                return {
                    controlled: true,
                    pageSize: RESULTS_PER_PAGE,
                    currentPage: page,
                    entryCount: releaseResponse?.count ?? 0,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
    })),
])
