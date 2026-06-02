import { combineUrl } from 'kea-router'

import { updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import {
    DEFAULT_DATE_RANGE,
    DEFAULT_SERVICE_NAMES,
    DEFAULT_SEVERITY_LEVELS,
} from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

/**
 * Build a Logs scene URL from viewer filters. This is the single source of truth for encoding
 * filters into the Logs scene's search params — it mirrors `logsSceneLogic`'s `actionToUrl` by
 * reusing the same `updateSearchParams` helper and `DEFAULT_*` constants, so a URL produced here
 * round-trips through the scene's `urlToAction`. Only fields present in `filters` are considered;
 * values equal to their default are omitted to keep the URL clean.
 */
export function getLogsSceneUrl(filters: Partial<LogsViewerFilters>): string {
    const params: Params = {}
    if (filters.searchTerm !== undefined) {
        updateSearchParams(params, 'searchTerm', filters.searchTerm, '')
    }
    if (filters.filterGroup !== undefined) {
        updateSearchParams(params, 'filterGroup', filters.filterGroup, DEFAULT_UNIVERSAL_GROUP_FILTER)
    }
    if (filters.dateRange !== undefined) {
        updateSearchParams(params, 'dateRange', filters.dateRange, DEFAULT_DATE_RANGE)
    }
    if (filters.severityLevels !== undefined) {
        updateSearchParams(params, 'severityLevels', filters.severityLevels, DEFAULT_SEVERITY_LEVELS)
    }
    if (filters.serviceNames !== undefined) {
        updateSearchParams(params, 'serviceNames', filters.serviceNames, DEFAULT_SERVICE_NAMES)
    }
    return combineUrl(urls.logs(), params).url
}
