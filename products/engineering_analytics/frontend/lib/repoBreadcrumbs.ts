import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { withScope } from './scope'

/** The crumbs every page shares, so the top bar reads the same on detail pages as on tabs. */
export function repoBreadcrumbs(
    repo: string | null,
    searchParams: Record<string, string | undefined> = {},
    sourceId: string | null = null
): Breadcrumb[] {
    return [
        {
            key: 'EngineeringAnalytics',
            name: 'Engineering analytics',
            path: withScope(urls.engineeringAnalytics(repo), searchParams, sourceId),
            iconType: 'health',
        },
        ...(repo ? [{ key: ['EngineeringAnalyticsRepo', repo], name: repo, iconType: 'health' } as Breadcrumb] : []),
    ]
}
