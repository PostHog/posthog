import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { WarehouseSuggestionApi } from './generated/api.schemas'

type ModelPageTab = Parameters<typeof urls.nodeDetail>[1]

const SAVED_QUERY_LOOKUP = { lookup: 'saved_query' }

export function subjectUrl(suggestion: WarehouseSuggestionApi, tab?: ModelPageTab): string {
    if (suggestion.subject_kind === 'saved_query') {
        return combineUrl(urls.nodeDetail(suggestion.subject_id, tab), SAVED_QUERY_LOOKUP).url
    }
    if (suggestion.subject_source_id && suggestion.subject_schema_id) {
        return urls.dataWarehouseSourceSchema(`managed-${suggestion.subject_source_id}`, suggestion.subject_schema_id)
    }
    return urls.dataWarehouseSource(`self-managed-${suggestion.subject_id}`)
}
