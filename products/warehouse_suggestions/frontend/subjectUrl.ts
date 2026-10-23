import { urls } from 'scenes/urls'

import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'

import type { WarehouseSuggestionApi } from './generated/api.schemas'

const TABLE_PREVIEW_LIMIT = 100

function escapeTableName(name: string): string {
    return name.split('.').map(escapeRawPropertyAsHogQLIdentifier).join('.')
}

export function subjectUrl(suggestion: WarehouseSuggestionApi): string {
    if (suggestion.subject_kind === 'table') {
        const table = escapeTableName(suggestion.payload.subject_name)
        return urls.sqlEditor({ query: `SELECT * FROM ${table} LIMIT ${TABLE_PREVIEW_LIMIT}` })
    }
    return urls.sqlEditor({ view_id: suggestion.subject_id })
}
