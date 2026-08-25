import { combineUrl } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { DateRange } from '~/queries/schema/schema-general'

/** Extra viewer filters to pin alongside the service. Keys are the URL params logsSceneLogic reads. */
export interface ServiceViewerFilters {
    severityLevels?: string[]
    dateRange?: DateRange
}

/**
 * Viewer tab scoped to one service. logsSceneLogic reads `serviceNames` back off the URL, and
 * the list has to go in as a list: a scalar comes back through `parseTagsFilter`'s
 * comma-separated path, so `checkout,v2` would arrive as two services. Any severity list passed
 * alongside it goes in the same way.
 */
export function serviceViewerUrl(serviceName: string, filters: ServiceViewerFilters = {}): string {
    return combineUrl(urls.currentProject(urls.logs()), {
        activeTab: 'viewer',
        serviceNames: [serviceName],
        ...filters,
    }).url
}

export function copyServiceDeepLink(serviceName: string): void {
    const full = urls.absolute(serviceViewerUrl(serviceName))
    void navigator.clipboard.writeText(full).then(
        () => lemonToast.success('Link copied'),
        () => lemonToast.error('Could not copy link')
    )
}
