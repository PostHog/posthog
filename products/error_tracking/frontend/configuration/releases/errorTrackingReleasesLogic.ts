import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import type { errorTrackingReleasesLogicType } from './errorTrackingReleasesLogicType'

import { Breadcrumb } from '~/types'

import { PaginationManual } from '@posthog/lemon-ui'

export const RESULTS_PER_PAGE = 15

export type ErrorTrackingReleaseResponse = CountedPaginatedResponse<ErrorTrackingRelease>

export const errorTrackingReleasesLogic = kea<errorTrackingReleasesLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingReleasesLogic']),
    props({}),

    actions({
        loadReleases: () => ({}),
        deleteRelease: (id: string) => ({ id }),
        setPage: (page: number) => ({ page }),
    }),

    reducers({
        page: [
            1 as number,
            {
                setPage: (_, { page }) => page,
            },
        ],
    }),

    loaders(({ values }) => ({
        releaseResponse: [
            null as ErrorTrackingReleaseResponse | null,
            {
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
        ],
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
            (releaseResponse: ErrorTrackingReleaseResponse | null) => releaseResponse?.results || [],
        ],
        pagination: [
            (s) => [s.page, s.releaseResponse],
            (page: number, releaseResponse: ErrorTrackingReleaseResponse | null): PaginationManual => {
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
        deleteRelease: async ({ id }) => {
            await api.errorTracking.releases.delete(id)
            actions.loadReleases()
        },
        setPage: () => actions.loadReleases(),
    })),
])
